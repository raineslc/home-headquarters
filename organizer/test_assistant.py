import copy
import uuid
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from .models import Household, Membership, FamilyMember, Activity, Task, AssistantPlan, AssistantUsage
from .assistant_service import validate_proposal, AssistantUnavailable

@override_settings(SECURE_SSL_REDIRECT=False, OPENAI_API_KEY='test-only', STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AssistantTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Test household')
        self.other = Household.objects.create(name='Other household')
        self.parent = get_user_model().objects.create_user('parent@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        self.child = FamilyMember.objects.create(household=self.house, name='Logan', role='child')
        self.foreign = FamilyMember.objects.create(household=self.other, name='Other child', role='child')
        self.client.force_login(self.parent)
        event = dict(title='Birthday party', start_date='2026-10-17', end_date='2026-10-17', start_time='14:00', end_time='16:00', all_day=False, participants=[str(self.child.pk)], location='', notes='', reminder_minutes=60, repeat=None)
        task = dict(title='Buy a gift', assignee=None, due_date='2026-10-16', due_time=None, high_priority=False, notes='Suggested deadline', reminder_minutes=1440, search_prompt='birthday gift ideas', search_questions='What age and budget?', repeat=None)
        self.proposal = dict(reply='Draft only', questions=['What age and budget?'], event=event, tasks=[dict(task, title=title) for title in ['Buy a gift', 'Wrap the gift', 'Confirm the address']])

    def draft(self, proposal=None):
        with patch('organizer.assistant.propose', return_value=copy.deepcopy(proposal or self.proposal)) as provider:
            data = {'prompt': 'Logan has a birthday party Saturday at 2 PM. We need a gift.', 'request_key': str(uuid.uuid4())}
            response = self.client.post('/assistant/', data)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.post('/assistant/', data).url, response.url)
            provider.assert_called_once()
        plan = AssistantPlan.objects.latest('created_at')
        self.assertFalse(Activity.objects.exists())
        self.assertFalse(Task.objects.exists())
        self.assertContains(self.client.get(response.url), 'Buy a gift')
        return plan

    def post_data(self, plan, action='approve_all'):
        data = {'version': plan.version, 'action': action}
        for suggestion in plan.suggestions.filter(revision=plan.revision):
            for key, value in suggestion.payload.items():
                if value is not None:
                    data[f'{suggestion.pk}-{key}'] = value
        return data

    def test_approve_all_links_records_and_retries_are_idempotent(self):
        plan = self.draft()
        data = self.post_data(plan)
        url = f'/assistant/{plan.pk}/'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        event = Activity.objects.get()
        self.assertEqual(Task.objects.filter(activity=event).count(), 3)
        self.assertEqual(event.reminder_minutes, 60)
        task = Task.objects.get(title='Buy a gift')
        self.client.post(f'/tasks/{task.pk}/complete/', {'version': task.version})
        suggestion = plan.suggestions.get(task=task)
        self.assertEqual(suggestion.status, 'approved')
        self.assertIsNotNone(Task.objects.get(pk=task.pk).completed_at)
        self.assertContains(self.client.get(url), 'Approved')

    def test_missing_end_time_blocks_atomic_approval(self):
        proposal = copy.deepcopy(self.proposal)
        proposal['event']['end_time'] = None
        plan = self.draft(proposal)
        response = self.client.post(f'/assistant/{plan.pk}/', self.post_data(plan))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a time')
        self.assertFalse(Activity.objects.exists())
        self.assertFalse(Task.objects.exists())

    def test_individual_edits_dismissal_and_approval(self):
        plan = self.draft()
        url = f'/assistant/{plan.pk}/'
        event = plan.suggestions.get(kind='event')
        task = plan.suggestions.filter(kind='task').first()
        self.assertContains(self.client.post(url, self.post_data(plan, f'approve:{task.pk}')), 'Approve or dismiss the event first')
        data = self.post_data(plan, f'save:{task.pk}')
        data[f'{task.pk}-title'] = 'Pick a book'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertFalse(Task.objects.exists())
        plan.refresh_from_db()
        self.client.post(url, self.post_data(plan, f'dismiss:{event.pk}'))
        plan.refresh_from_db()
        self.client.post(url, self.post_data(plan, f'approve:{task.pk}'))
        self.assertEqual(Task.objects.get().title, 'Pick a book')
        self.assertIsNone(Task.objects.get().activity)
        self.assertFalse(Activity.objects.exists())

    def test_household_scope_stale_edits_and_untrusted_member_ids(self):
        plan = self.draft()
        data = self.post_data(plan)
        event = plan.suggestions.get(kind='event')
        data[f'{event.pk}-participants'] = [str(self.foreign.pk)]
        self.assertEqual(self.client.post(f'/assistant/{plan.pk}/', data).status_code, 200)
        self.assertFalse(Activity.objects.exists())
        data['version'] = 999
        self.assertEqual(self.client.post(f'/assistant/{plan.pk}/', data).status_code, 409)
        plan.household = self.other
        plan.save()
        self.assertEqual(self.client.get(f'/assistant/{plan.pk}/').status_code, 404)
        self.assertEqual(self.client.post(f'/assistant/{plan.pk}/', data).status_code, 404)

    def test_clarification_preserves_history_and_creates_no_records(self):
        plan = self.draft()
        with patch('organizer.assistant.propose', return_value=copy.deepcopy(self.proposal)):
            response = self.client.post(f'/assistant/{plan.pk}/revise/', {'version': plan.version, 'answer': 'The party ends at 4 PM.'})
        self.assertEqual(response.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.revision, 2)
        self.assertEqual(plan.suggestions.filter(status='superseded').count(), 4)
        self.assertFalse(Task.objects.exists())
        self.assertFalse(Activity.objects.exists())

    def test_invalid_ai_output_and_false_action_claims(self):
        data = copy.deepcopy(self.proposal)
        data['reply'] = 'I scheduled everything and bought the gift.'
        data['event']['end_time'] = None
        data['tasks'][0]['search_prompt'] = 'Logan birthday gift parent@example.test'
        result = validate_proposal(data, self.house)
        self.assertIn('Nothing has been added', result['reply'])
        self.assertIn('What time does the activity end?', result['questions'])
        self.assertNotIn('Logan', result['tasks'][0]['search_prompt'])
        self.assertNotIn('@', result['tasks'][0]['search_prompt'])
        data = copy.deepcopy(self.proposal)
        data['event']['participants'] = [str(self.foreign.pk)]
        with self.assertRaises(ValueError):
            validate_proposal(data, self.house)
        data = copy.deepcopy(self.proposal)
        data['tasks'][0]['high_priority'] = 'false'
        with self.assertRaises(ValueError):
            validate_proposal(data, self.house)

    def test_failure_is_saved_without_creating_plans_and_counted(self):
        with patch('organizer.assistant.propose', side_effect=AssistantUnavailable('AI did not respond in time.')):
            self.client.post('/assistant/', {'prompt': 'A party', 'request_key': uuid.uuid4()})
        self.assertEqual(AssistantPlan.objects.get().status, 'error')
        self.assertEqual(AssistantUsage.objects.get().attempts, 1)
        self.assertFalse(Activity.objects.exists())

    def test_search_requires_explicit_submit_and_never_completes_task(self):
        task = Task.objects.create(household=self.house, title='Gift', search_prompt='gift ideas')
        url = f'/tasks/{task.pk}/search/'
        self.assertContains(self.client.get(url), 'Google')
        response = self.client.post(url, {'version': task.version, 'query': 'books age 8 under $25'})
        self.assertEqual(response.url, 'https://www.google.com/search?q=books+age+8+under+%2425')
        task.refresh_from_db()
        self.assertIsNone(task.completed_at)
        task.household = self.other
        task.save()
        self.assertEqual(self.client.get(url).status_code, 404)
