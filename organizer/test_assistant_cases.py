import copy
import uuid
from datetime import date
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from .assistant import generate
from .assistant_cases import CASES, FAMILY, resolve, run_checks
from .assistant_service import validate_proposal
from .models import Activity, AssistantPlan, AssistantSuggestion, FamilyMember, Household, Membership, Task

def event(**changes):
    value = dict(title='Activity', start_date=None, end_date=None, start_time=None, end_time=None, all_day=False, participants=[],
                 location='', notes='', reminder_minutes=None, repeat=None)
    value.update(changes)
    return value

def task(**changes):
    value = dict(title='Task', assignee=None, due_date=None, due_time=None, high_priority=False, notes='', reminder_minutes=None,
                 search_prompt='', search_questions='', repeat=None)
    value.update(changes)
    return value

def weekly(day, ends='never', until=None, count=None):
    return dict(frequency='WEEKLY', interval=1, weekdays=[day], monthly_by='day', ends=ends, until=until, count=count)

def plan(event_value=None, tasks=(), questions=()):
    return dict(reply='Model prose is replaced by the server.', questions=list(questions), event=event_value, tasks=list(tasks))

BIRTHDAY_EVENT = event(title='Birthday party', start_date='2026-10-17', end_date='2026-10-17', start_time='14:00', participants=['{Logan}'])
BIRTHDAY_TASKS = [task(title='Buy and wrap a gift', due_date='2026-10-16', notes='Pick a gift, then wrap it with a card.',
                       search_prompt='birthday gift ideas', search_questions='Recipient age and budget?'),
                  task(title='Confirm the party address', due_date='2026-10-15')]

# Recorded examples of acceptable answers; each must pass every check of its case.
GOOD = {
    'birthday_recipient': plan(BIRTHDAY_EVENT, BIRTHDAY_TASKS, ['Whose birthday is it?', "How old is the birthday child, and what's your gift budget?", 'When does the party end?']),
    'same_day_weekday': plan(event(title='Soccer game', start_date='2026-10-17', end_date='2026-10-17', start_time='10:00', participants=['{Henry}']),
                             questions=['Is the game today (Oct 17) or next Saturday (Oct 24)?', 'When does it end?']),
    'sparse_input': plan(event(title='Soccer'), questions=['What date and time is soccer?', 'Who is going?']),
    'task_only': plan(None, [task(title='Renew passport', due_date='2026-11-30', search_prompt='passport renewal requirements')]),
    'repeating_activity': plan(event(title='Swim lessons', start_date='2026-10-20', end_date='2026-10-20', start_time='16:00', end_time='17:00',
                                     participants=['{Henry}'], repeat=weekly('TU', 'until', '2026-12-15'))),
    'repeating_task': plan(None, [task(title='Take out the recycling', due_date='2026-10-15', due_time='18:00', repeat=weekly('TH'))]),
    'clarification_keeps_edits': plan(dict(BIRTHDAY_EVENT, end_time='16:00'), [task(title='Buy a book as a gift', due_date='2026-10-16'),
                                                                                 task(title='Wrap the gift', due_date='2026-10-16')]),
}

# Known-bad answers and the check each must trip.
BAD = [
    ('birthday_recipient', 'Activity title does not assume whose birthday it is', lambda p: p['event'].update(title="Logan's birthday party")),
    ('birthday_recipient', 'No task assumes the gift is for Logan', lambda p: p['tasks'][0].update(title="Buy Logan's birthday gift")),
    ('birthday_recipient', 'End time is not invented (left empty and asked)', lambda p: p['event'].update(end_time='16:00')),
    ('birthday_recipient', 'Asks the recipient age and gift budget', lambda p: p.update(questions=['Whose birthday is it?'])),
    ('birthday_recipient', 'No high priority or reminders unless asked', lambda p: p['tasks'][1].update(high_priority=True)),
    ('birthday_recipient', 'Buying and wrapping the gift are one task', lambda p: p.update(tasks=[
        task(title='Buy a gift', due_date='2026-10-16'), task(title='Wrap the gift', due_date='2026-10-16'), task(title='Confirm the party address')])),
    ('task_only', 'Keeps the plan to a few tasks (at most 4)', lambda p: p.update(tasks=[task(title=f'Passport step {n}') for n in range(5)])),
    ('task_only', 'Task-only request has no activity', lambda p: p.update(event=event(title='Passport'))),
    ('repeating_activity', 'Activity repeats weekly on TU until 2026-12-15', lambda p: p['event'].update(repeat=None)),
    ('repeating_task', 'A task repeats weekly on TH', lambda p: p['tasks'][0].update(repeat=weekly('FR'), due_date='2026-10-16')),
    ('clarification_keeps_edits', 'Does not bring back the dismissed address task', lambda p: p['tasks'].append(task(title='Confirm the party address'))),
    ('clarification_keeps_edits', 'Does not ask again for details already given', lambda p: p.update(questions=['What is your budget?'])),
    ('sparse_input', 'No time, location or end invented from a one-word request', lambda p: p['event'].update(start_time='09:00', end_time='10:00')),
]

class AssistantCaseTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Evaluation fixture')
        self.ids = {name: str(FamilyMember.objects.create(household=self.house, name=name, role=role).pk) for name, role in FAMILY}
        self.cases = {case.name: case for case in CASES}

    def evaluate(self, name, sample):
        result = validate_proposal(resolve(copy.deepcopy(sample), self.ids), self.house)
        return dict(run_checks(self.cases[name], result, self.ids))

    def test_every_case_has_a_passing_sample(self):
        self.assertEqual(set(GOOD), set(self.cases))
        for name, sample in GOOD.items():
            with self.subTest(case=name):
                outcomes = self.evaluate(name, sample)
                self.assertEqual([text for text, passed in outcomes.items() if not passed], [])

    def test_known_bad_answers_are_caught(self):
        for name, description, damage in BAD:
            with self.subTest(case=name, check=description):
                sample = copy.deepcopy(GOOD[name])
                damage(sample)
                outcomes = self.evaluate(name, sample)
                self.assertIn(description, outcomes)
                self.assertFalse(outcomes[description])

    def test_live_command_requires_a_key_and_rolls_back(self):
        from django.core.management import call_command, CommandError
        with override_settings(OPENAI_API_KEY=''), self.assertRaises(CommandError):
            call_command('assistant_eval')
        households = Household.objects.count()
        with override_settings(OPENAI_API_KEY='test-only'), patch('organizer.management.commands.assistant_eval.propose',
                                                                 side_effect=lambda house, turns, drafts, today: validate_proposal(
                                                                     resolve(copy.deepcopy(GOOD['task_only']), {}), house)):
            call_command('assistant_eval', case=['task_only'], stdout=open(__import__('os').devnull, 'w'))
        self.assertEqual(Household.objects.count(), households)

@override_settings(SECURE_SSL_REDIRECT=False, OPENAI_API_KEY='test-only', STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AssistantGuardTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.parent = get_user_model().objects.create_user('parent@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        self.client.force_login(self.parent)
        self.child = FamilyMember.objects.create(household=self.house, name='Logan', role='child')

    def test_duplicate_tasks_and_questions_are_removed(self):
        result = validate_proposal(plan(None, [task(title='Buy a gift'), task(title='buy a gift!'), task(title='Wrap the gift')],
                                        ['What is the budget?', 'what is the budget', 'Whose birthday is it?']), self.house)
        self.assertEqual([t['title'] for t in result['tasks']], ['Buy a gift', 'Wrap the gift'])
        self.assertEqual(result['questions'], ['What is the budget?', 'Whose birthday is it?'])

    def test_unusable_repeat_becomes_a_question(self):
        mismatch = event(title='Swim', start_date='2026-10-21', end_date='2026-10-21', all_day=True, repeat=weekly('TU'))  # a Wednesday
        result = validate_proposal(plan(mismatch), self.house)
        self.assertEqual(result['event']['repeat'], '')
        self.assertTrue(any('How should "Swim" repeat?' in q for q in result['questions']))
        bad_interval = event(title='Swim', start_date='2026-10-20', end_date='2026-10-20', all_day=True, repeat=dict(weekly('TU'), interval=0))
        result = validate_proposal(plan(bad_interval), self.house)
        self.assertEqual(result['event']['repeat'], '')
        good = event(title='Swim', start_date='2026-10-20', end_date='2026-10-20', all_day=True, repeat=weekly('TU', 'count', count=8))
        result = validate_proposal(plan(good), self.house)
        self.assertEqual((result['event']['repeat'], result['event']['weekdays'], result['event']['count']), ('WEEKLY', ['TU'], 8))

    def draft(self, proposal):
        with patch('organizer.assistant.propose', return_value=validate_proposal(copy.deepcopy(proposal), self.house)):
            response = self.client.post('/assistant/', {'prompt': 'Swim lessons every Tuesday', 'request_key': str(uuid.uuid4())})
        return AssistantPlan.objects.get(pk=response.url.rstrip('/').split('/')[-1])

    def approve_all(self, plan_object):
        data = {'version': plan_object.version, 'action': 'approve_all'}
        for suggestion in plan_object.suggestions.filter(revision=plan_object.revision):
            for key, value in suggestion.payload.items():
                if value is not None and value != []:
                    data[f'{suggestion.pk}-{key}'] = value
        return self.client.post(f'/assistant/{plan_object.pk}/', data)

    def test_approving_repeating_suggestions_creates_series(self):
        proposal = plan(event(title='Swim lessons', start_date='2026-10-20', end_date='2026-10-20', start_time='16:00', end_time='17:00',
                              participants=[str(self.child.pk)], repeat=weekly('TU', 'until', '2026-12-15')),
                        [task(title='Pack swim bag', due_date='2026-10-20', repeat=weekly('TU'))])
        plan_object = self.draft(proposal)
        self.assertContains(self.client.get(f'/assistant/{plan_object.pk}/'), 'Repeats')
        self.assertEqual(self.approve_all(plan_object).status_code, 302)
        series = Activity.objects.get()
        self.assertEqual(series.recurrence, 'FREQ=WEEKLY;BYDAY=TU;UNTIL=20261215')
        chore = Task.objects.get()
        self.assertEqual((chore.recurrence, chore.recurrence_start, chore.activity), ('FREQ=WEEKLY;BYDAY=TU', date(2026, 10, 20), series))
        self.assertIsNotNone(chore.series_key)

    def test_clarification_does_not_revive_dismissed_items(self):
        first = plan(None, [task(title='Buy a gift'), task(title='Confirm the address')])
        plan_object = self.draft(first)
        dismissed = plan_object.suggestions.get(payload__title='Confirm the address')
        AssistantSuggestion.objects.filter(pk=dismissed.pk).update(status='dismissed')
        AssistantPlan.objects.filter(pk=plan_object.pk).update(status='generating')
        plan_object.refresh_from_db()
        again = validate_proposal(plan(None, [task(title='Buy a gift'), task(title='confirm the address.'), task(title='Wrap the gift')]), self.house)
        with patch('organizer.assistant.propose', return_value=again):
            generate(plan_object)
        titles = list(plan_object.suggestions.filter(revision=2).values_list('payload__title', flat=True))
        self.assertEqual(sorted(titles), ['Buy a gift', 'Wrap the gift'])
