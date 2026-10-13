from datetime import date
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from .models import Household, Membership, FamilyMember, Activity, Task, LunchPlan
from .planner_forms import ActivityForm

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PlannerTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.other = Household.objects.create(name='Other fixture family')
        parent = get_user_model().objects.create_user('fixture@example.test')
        Membership.objects.create(user=parent, household=self.house)
        self.client.force_login(parent)
        self.child = FamilyMember.objects.create(household=self.house, name='Fixture child', role='child')
        self.foreign = FamilyMember.objects.create(household=self.other, name='Private child', role='child')

    def activity_data(self):
        return {'title': 'Party', 'start_date': '2026-10-17', 'end_date': '2026-10-17', 'start_time': '14:00', 'end_time': '16:00', 'participants': [str(self.child.pk)], 'version': 0}

    def test_create_edit_activity_link_task_and_complete(self):
        self.assertEqual(self.client.post('/plan/activity/new/', self.activity_data()).status_code, 302)
        event = Activity.objects.get()
        self.assertEqual(event.household, self.house)
        self.assertEqual(list(event.participants.all()), [self.child])
        self.assertEqual(self.client.post('/plan/task/new/', {'title': 'Buy a gift', 'assignee': str(self.child.pk), 'activity': str(event.pk), 'due_date': '2026-10-16', 'version': 0}).status_code, 302)
        task = Task.objects.get()
        self.assertContains(self.client.get(f'/activity/{event.pk}/'), 'Buy a gift')
        self.assertContains(self.client.get('/?date=2026-10-17'), 'Party')
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/complete/', {'version': 1}).status_code, 302)
        task.refresh_from_db()
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/complete/', {'version': 1}).status_code, 409)
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/complete/', {'version': 2}).status_code, 302)
        task.refresh_from_db()
        self.assertIsNone(task.completed_at)

    def test_cross_household_ids_and_stale_edits_rejected(self):
        values = self.activity_data()
        values['participants'] = [str(self.foreign.pk)]
        self.assertEqual(self.client.post('/plan/activity/new/', values).status_code, 200)
        self.assertFalse(Activity.objects.exists())
        self.assertEqual(self.client.get(f'/plan/member/{self.foreign.pk}/edit/').status_code, 404)
        self.assertEqual(self.client.post('/plan/task/new/', {'title': 'Invalid', 'assignee': str(self.foreign.pk), 'version': 0}).status_code, 200)
        self.assertFalse(Task.objects.exists())
        values = {'name': 'Changed', 'role': 'child', 'color': 'green', 'version': 1}
        self.assertEqual(self.client.post(f'/plan/member/{self.child.pk}/edit/', values).status_code, 302)
        self.assertEqual(self.client.post(f'/plan/member/{self.child.pk}/edit/', values).status_code, 409)
        self.assertEqual(self.client.post(f'/plan/member/{self.child.pk}/remove/', {'version': 1}).status_code, 409)

    def test_lunch_bulk_and_undo_are_scoped_and_versioned(self):
        values = {'child': str(self.child.pk), 'dates': ['2026-10-12', '2026-10-13'], 'choice': 'pack', 'version': 1}
        self.assertEqual(self.client.post('/lunches/?date=2026-10-12', values).status_code, 302)
        self.assertEqual(LunchPlan.objects.filter(choice='pack').count(), 2)
        self.assertEqual(self.client.post('/lunches/?date=2026-10-12', values).status_code, 409)
        self.assertEqual(self.client.post('/lunches/undo/').status_code, 302)
        self.assertEqual(LunchPlan.objects.filter(choice='pack').count(), 0)
        self.assertEqual(self.client.post('/lunches/undo/').status_code, 400)
        values['child'] = str(self.foreign.pk)
        self.assertEqual(self.client.post('/lunches/', values).status_code, 404)

    def test_all_day_multiday_and_dst_validation(self):
        values = self.activity_data()
        values.update(all_day=True, start_date='2026-10-15', end_date='2026-10-18')
        self.client.post('/plan/activity/new/', values)
        event = Activity.objects.get()
        self.assertIsNone(event.start_time)
        response = self.client.get('/?date=2026-10-12')
        occupied = [cell['date'] for cell in response.context['cells'] if event in cell['events']]
        self.assertEqual(occupied, [date(2026, 10, d) for d in (15, 16, 17, 18)])
        values = self.activity_data()
        values.update(start_date='2026-03-08', end_date='2026-03-08', start_time='02:30', end_time='04:00')
        form = ActivityForm(values, household=self.house)
        self.assertFalse(form.is_valid())
        self.assertIn('start_time', form.errors)

    def test_views_render_and_archived_members_remain_linked(self):
        for url in ['/', '/?view=month', '/?view=agenda', '/tasks/', '/family/', '/lunches/', '/settings/', '/plan/activity/new/', '/plan/task/new/', '/plan/member/new/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.post('/plan/activity/new/', self.activity_data())
        self.client.post(f'/plan/member/{self.child.pk}/remove/', {'version': 1})
        self.child.refresh_from_db()
        self.assertTrue(self.child.archived)
        self.assertEqual(Activity.objects.get().participants.count(), 1)
