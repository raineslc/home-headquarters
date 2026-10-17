import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from .models import FamilyMember, Household, Membership, Task
from .planner import next_task
from .recovery import snapshot

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ChoreTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.other = Household.objects.create(name='Other family')
        parent = get_user_model().objects.create_user('fixture@example.test')
        Membership.objects.create(user=parent, household=self.house)
        self.client.force_login(parent)
        self.adult = FamilyMember.objects.create(household=self.house, name='Chris', role='parent', color='blue')
        self.today = timezone.localdate(timezone=ZoneInfo(self.house.timezone))

    def chore(self, title='Mow', rule='FREQ=WEEKLY;BYDAY=SA', due=date(2026, 10, 17), after=True, **extra):
        return Task.objects.create(household=self.house, title=title, due_date=due, recurrence=rule, recurrence_start=due,
                                   series_key=uuid.uuid4(), repeat_after_done=after, **extra)

    def test_after_done_counts_from_completion_once(self):
        mow = self.chore()
        following = next_task(mow, done_on=date(2026, 10, 20))  # mowed three days late
        self.assertEqual((following.due_date, following.repeat_after_done), (date(2026, 10, 27), True))
        # Reopened and completed again the next day: still one next task.
        self.assertEqual(next_task(mow, done_on=date(2026, 10, 21)), following)
        self.assertEqual(Task.objects.filter(series_key=mow.series_key).count(), 2)
        fixed = self.chore('Trash', after=False)
        self.assertEqual(next_task(fixed, done_on=date(2026, 10, 20)).due_date, date(2026, 10, 24))

    def test_early_completion_interval_and_ends(self):
        wipe = self.chore('Wipe counters', 'FREQ=DAILY', due=date(2026, 10, 20))
        self.assertEqual(next_task(wipe, done_on=date(2026, 10, 17)).due_date, date(2026, 10, 21))  # never before the current due day
        filters = self.chore('Change filter', 'FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=17')
        self.assertEqual(next_task(filters, done_on=date(2026, 10, 18)).due_date, date(2027, 1, 18))
        last = self.chore('Until', 'FREQ=WEEKLY;BYDAY=SA;UNTIL=20261020')
        self.assertIsNone(next_task(last, done_on=date(2026, 10, 17)))
        counted = self.chore('Twice', 'FREQ=WEEKLY;BYDAY=SA;COUNT=2')
        second = next_task(counted, done_on=date(2026, 10, 17))
        self.assertIsNone(next_task(second, done_on=date(2026, 10, 24)))

    def test_form_saves_after_done_and_ignores_weekdays(self):
        page = self.client.get('/plan/task/new/?chore=1')
        self.assertContains(page, 'A set time after it’s done')
        self.assertContains(page, '<option value="WEEKLY" selected>', html=False)
        data = {'title': 'Mow the lawn', 'assignee': str(self.adult.pk), 'due_date': '2026-10-18', 'version': 0, 'repeat': 'WEEKLY',
                'repeat_mode': 'after', 'interval': 1, 'weekdays': ['MO', 'TH'], 'ends': 'never', 'monthly_by': 'day'}
        response = self.client.post('/plan/task/new/?chore=1', data)
        self.assertRedirects(response, '/chores/', fetch_redirect_response=False)
        task = Task.objects.get(title='Mow the lawn')
        self.assertEqual((task.recurrence, task.repeat_after_done), ('FREQ=WEEKLY;BYDAY=SU', True))
        self.client.post(f'/plan/task/{task.pk}/edit/', dict(data, version=task.version, repeat_mode='schedule', weekdays=['SU']))
        task.refresh_from_db()
        self.assertFalse(task.repeat_after_done)
        self.assertEqual(snapshot(self.house)['tasks'][0]['repeat_after_done'], False)

    def test_chores_page_groups_people_and_completes_in_place(self):
        overdue = self.chore('Laundry', due=self.today - timedelta(days=2), after=False)
        self.chore('Mow', 'FREQ=WEEKLY;INTERVAL=2;BYDAY=' + 'MO TU WE TH FR SA SU'.split()[self.today.weekday()], due=self.today, assignee=self.adult)
        Task.objects.create(household=self.house, title='Buy a gift', due_date=self.today)
        Task.objects.create(household=self.other, title='Other family chore', due_date=self.today, recurrence='FREQ=DAILY',
                            recurrence_start=self.today, series_key=uuid.uuid4())
        page = self.client.get('/chores/')
        text = page.content.decode()
        self.assertLess(text.index('Household'), text.index('Chris'))
        self.assertContains(page, 'Every 2 weeks after it’s done')
        self.assertContains(page, 'Overdue')
        self.assertNotContains(page, 'Buy a gift')
        self.assertNotContains(page, 'Other family chore')
        response = self.client.post(f'/tasks/{overdue.pk}/complete/', {'version': overdue.version, 'origin': 'chores'})
        self.assertRedirects(response, '/chores/', fetch_redirect_response=False)
        self.assertContains(self.client.get('/chores/'), 'Done in the last 7 days (1)')

    def test_empty_state_and_navigation(self):
        page = self.client.get('/chores/')
        self.assertContains(page, 'No chores yet')
        self.assertContains(page, 'href="/chores/" aria-current="page"')
