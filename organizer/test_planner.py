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
        self.assertEqual(self.client.post('/lunches/?date=2026-10-12', values).status_code, 404)

    def test_quick_forms_save_and_keep_invalid_input_on_overview(self):
        values = {'quick_kind': 'activity', 'activity-title': 'Quick party', 'activity-start_date': '2026-10-17', 'activity-start_time': '14:00', 'activity-end_time': '16:00', 'activity-version': 0}
        self.assertEqual(self.client.post('/', values).status_code, 302)
        event = Activity.objects.get()
        self.assertEqual(event.start_date, event.end_date)
        self.assertEqual(event.household, self.house)
        values['activity-end_time'] = '13:00'
        response = self.client.post('/', values)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The end must be after the start.')
        self.assertEqual(Activity.objects.count(), 1)
        response = self.client.post('/', {'quick_kind': 'task', 'task-title': 'Urgent prep', 'task-version': 0, 'task-high_priority': 'on', 'task-assignee': str(self.foreign.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.exists())
        self.assertEqual(self.client.post('/', {'quick_kind': 'task', 'task-title': 'Urgent prep', 'task-version': 0, 'task-high_priority': 'on'}).status_code, 302)
        self.assertTrue(Task.objects.get().high_priority)

    def test_priority_sorts_first_even_after_eight_ordinary_tasks(self):
        for i in range(9):
            Task.objects.create(household=self.house, title=f'Ordinary {i}', due_date='2026-10-01')
        urgent = Task.objects.create(household=self.house, title='Urgent future', due_date='2027-01-01', high_priority=True)
        self.assertEqual(list(self.client.get('/tasks/').context['tasks'])[0], urgent)
        self.assertEqual(list(self.client.get('/?date=2026-10-12').context['priorities'])[0], urgent)

    def test_month_lunch_selection_handles_leap_year_and_undo(self):
        response = self.client.get('/lunches/?date=2028-02-15')
        self.assertEqual(response.context['day'], date(2028, 2, 1))
        self.assertIn(date(2028, 2, 29), response.context['days'])
        self.assertEqual(len(response.context['days']), 21)
        values = {'child': str(self.child.pk), 'all_month': '1', 'choice': 'school', 'version': 1}
        self.assertEqual(self.client.post('/lunches/?date=2028-02-15', values).status_code, 302)
        self.assertEqual(LunchPlan.objects.filter(choice='school').count(), 21)
        self.assertEqual(self.client.post('/lunches/undo/').url, '/lunches/?date=2028-02-01')
        self.assertFalse(LunchPlan.objects.filter(choice='school').exists())

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
        event = Activity.objects.get()
        values = self.activity_data()
        values['version'] = event.version
        self.assertEqual(self.client.post(f'/plan/activity/{event.pk}/edit/', values).status_code, 302)
        self.assertEqual(event.participants.count(), 1)

    def test_agenda_is_a_rolling_seven_day_upcoming_list_with_tasks(self):
        from datetime import time, timedelta
        from zoneinfo import ZoneInfo
        from django.utils import timezone
        today = timezone.localdate(timezone=ZoneInfo(self.house.timezone))
        event = Activity.objects.create(household=self.house, title='Sixth-day game', start_date=today + timedelta(days=6), end_date=today + timedelta(days=6))
        timed = Task.objects.create(household=self.house, title='Timed task', assignee=self.child, activity=event, due_date=today + timedelta(days=3), due_time=time(9))
        urgent = Task.objects.create(household=self.house, title='Urgent untimed task', high_priority=True, due_date=today + timedelta(days=3))
        late = Task.objects.create(household=self.house, title='Overdue task', due_date=today - timedelta(days=2))
        Task.objects.create(household=self.house, title='Completed task', due_date=today + timedelta(days=1), completed_at=timezone.now())
        Task.objects.create(household=self.house, title='Eighth-day task', due_date=today + timedelta(days=7))
        Task.objects.create(household=self.other, title='Other household task', due_date=today)
        response = self.client.get('/?view=agenda')
        cells = response.context['cells']
        self.assertEqual([cell['date'] for cell in cells], [today + timedelta(days=i) for i in range(7)])
        self.assertIn(event, cells[6]['events'])
        self.assertEqual(cells[3]['tasks'], [urgent, timed])
        self.assertEqual(response.context['overdue'], [late])
        self.assertContains(response, 'Upcoming')
        self.assertContains(response, 'For Sixth-day game')
        self.assertContains(response, 'Fixture child')
        for hidden in ('Completed task', 'Other household task'):
            self.assertNotContains(response, hidden)
        self.assertNotIn('Eighth-day task', [t.title for cell in cells for t in cell['tasks']])
        later = self.client.get('/?view=agenda&date=' + (today + timedelta(days=10)).isoformat())
        self.assertEqual(later.context['cells'][0]['date'], today + timedelta(days=10))
        self.assertEqual(later.context['overdue'], [])
        # Week view still aligns to Monday and does not show the overdue list.
        week = self.client.get('/?date=' + today.isoformat())
        self.assertEqual(week.context['cells'][0]['date'].weekday(), 0)
        self.assertEqual(week.context['overdue'], [])

    def test_overview_shows_all_open_tasks_with_quick_filters(self):
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from django.utils import timezone
        today = timezone.localdate(timezone=ZoneInfo(self.house.timezone))
        def task(title, days=None, high=False, done=False):
            return Task.objects.create(household=self.house, title=title, high_priority=high,
                                       due_date=today + timedelta(days=days) if days is not None else None,
                                       completed_at=timezone.now() if done else None)
        overdue, today_task, tomorrow = task('Overdue', -3), task('Today', 0), task('Tomorrow', 1)
        week, later, undated = task('In seven days', 7), task('In eight days', 8), task('No date')
        urgent_later, urgent_undated = task('Urgent later', 30, high=True), task('Urgent undated', high=True)
        task('Done', 0, done=True)
        Task.objects.create(household=self.other, title='Other household', due_date=today)
        def shown(key=None):
            response = self.client.get('/' + (f'?tasks={key}' if key else ''))
            return response, list(response.context['priorities'])
        import uuid
        chore = Task.objects.create(household=self.house, title='Laundry', due_date=today, recurrence='FREQ=DAILY',
                                    recurrence_start=today, series_key=uuid.uuid4())
        response, everything = shown()
        self.assertEqual(everything, [urgent_later, urgent_undated, overdue, today_task, tomorrow, week, later, undated])
        self.assertEqual(list(response.context['chore_list']), [chore])
        # Counts cover tasks and chores; buckets don't overlap except high priority.
        self.assertEqual({f['key']: f['count'] for f in response.context['task_filters']}, {'overdue': 1, 'today': 2, 'week': 2, 'high': 2})
        self.assertEqual(response.context['summary'], {'tasks': 8, 'chores': 1, 'tasks_done': 1, 'chores_done': 0})
        self.assertContains(response, 'Tasks &amp; chores')
        self.assertContains(response, '1 task and 0 chores done this week')
        self.assertEqual(shown('high')[1], [urgent_later, urgent_undated])
        self.assertEqual(shown('overdue')[1], [overdue])
        self.assertEqual(shown('week')[1], [tomorrow, week])
        response, listed = shown('today')
        self.assertEqual((listed, list(response.context['chore_list'])), ([today_task], [chore]))
        self.assertContains(response, 'Showing due today')
        self.assertEqual(shown('bogus')[0].context['task_filter'], 'all')
        Task.objects.filter(household=self.house).update(completed_at=timezone.now())
        self.assertContains(self.client.get('/?tasks=today'), 'No tasks here.')


    def test_settings_shows_the_running_version(self):
        from unittest.mock import patch
        self.assertContains(self.client.get('/settings/'), 'Running a local build')
        with patch.dict('os.environ', {'RENDER_GIT_COMMIT': '790fc54b622eac38df1ac960511f1ecdb80169c2', 'RENDER_GIT_BRANCH': 'main'}):
            response = self.client.get('/settings/')
        self.assertContains(response, '<code>790fc54</code>')
        self.assertContains(response, 'https://github.com/raineslc/home-headquarters/commit/790fc54b622eac38df1ac960511f1ecdb80169c2')
        self.assertContains(response, 'from main')

    def test_version_uses_the_cloud_run_commit_when_present(self):
        from unittest.mock import patch
        env = {'APP_COMMIT': 'abcdef1234567890abcdef1234567890abcdef12', 'APP_BRANCH': 'main', 'RENDER_GIT_COMMIT': '1111111111111111111111111111111111111111'}
        with patch.dict('os.environ', env):
            response = self.client.get('/settings/')
        self.assertContains(response, '<code>abcdef1</code>')
        self.assertNotContains(response, '<code>1111111</code>')

    def test_default_view_is_a_rolling_five_weeks_and_week_tiles_show_more(self):
        from datetime import time, timedelta
        from zoneinfo import ZoneInfo
        from django.utils import timezone
        today = timezone.localdate(timezone=ZoneInfo(self.house.timezone))
        monday = today - timedelta(days=today.weekday())
        response = self.client.get('/')
        cells = response.context['cells']
        self.assertEqual(response.context['mode'], 'month')
        self.assertEqual([c['date'] for c in cells], [monday + timedelta(days=i) for i in range(35)])
        self.assertIn(today, [c['date'] for c in cells[:7]])  # today is on the top row
        self.assertTrue(cells[0]['month_label'])
        self.assertEqual((response.context['previous'], response.context['next']), (today - timedelta(days=28), today + timedelta(days=28)))
        later = self.client.get('/?date=' + (today + timedelta(days=28)).isoformat())
        self.assertEqual(later.context['cells'][0]['date'], monday + timedelta(days=28))
        event = Activity.objects.create(household=self.house, title='Recital', start_date=today, end_date=today,
                                        start_time=time(18), end_time=time(19, 30), location='School hall')
        Task.objects.create(household=self.house, title='Iron the shirt', due_date=today, due_time=time(17), assignee=self.child, activity=event)
        week = self.client.get('/?view=week')
        self.assertContains(week, '6:00 PM–7:30 PM')
        self.assertContains(week, 'School hall')
        self.assertContains(week, 'For Recital')
        month = self.client.get('/')
        self.assertNotContains(month, '6:00 PM–7:30 PM')
        self.assertContains(month, 'Recital')

