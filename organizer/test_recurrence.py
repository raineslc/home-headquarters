import json
from datetime import date, time, timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from .models import Activity, FamilyMember, Household, Membership, Task
from .recovery import snapshot
from .recurrence import build_rule, dates_between, describe, end_before, household_events, next_date, validate_rule, wall_time

class RuleTests(SimpleTestCase):
    def test_rules_build_describe_and_expand(self):
        anchor = date(2026, 10, 13)  # second Tuesday
        weekly = build_rule('WEEKLY', 2, anchor, ['TU', 'TH'], ends='count', count=4)
        self.assertEqual(weekly, 'FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH;COUNT=4')
        self.assertEqual(describe(weekly, anchor), 'Every 2 weeks on Tuesday, Thursday, 4 times')
        self.assertEqual(dates_between(weekly, anchor, anchor, date(2027, 1, 1)),
                         [date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 27), date(2026, 10, 29)])
        monthly = build_rule('MONTHLY', 1, anchor, monthly_by='weekday', ends='until', until=date(2027, 1, 31))
        self.assertEqual(describe(monthly, anchor), 'Every month on the second Tuesday, until Jan 31, 2027')
        self.assertEqual(dates_between(monthly, anchor, date(2026, 11, 1), date(2027, 3, 1)), [date(2026, 11, 10), date(2026, 12, 8), date(2027, 1, 12)])
        fifth = build_rule('MONTHLY', 1, date(2026, 10, 29), monthly_by='weekday')
        self.assertEqual(fifth, 'FREQ=MONTHLY;BYDAY=-1TH')
        self.assertEqual(next_date('FREQ=MONTHLY;BYMONTHDAY=31', date(2026, 10, 31), date(2026, 10, 31)), date(2026, 12, 31))
        self.assertEqual(next_date(weekly, anchor, date(2026, 10, 29)), None)
        self.assertEqual(end_before(weekly, anchor, date(2026, 10, 20)), 'FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH;UNTIL=20261015')
        self.assertEqual(end_before(weekly, anchor, anchor), '')
        self.assertEqual(describe(build_rule('YEARLY', 1, date(2027, 2, 14)), date(2027, 2, 14)), 'Every year on February 14')

    def test_invalid_rules_are_rejected(self):
        anchor = date(2026, 10, 13)
        for rule in ['', 'FREQ=HOURLY', 'FREQ=DAILY;COUNT=0', 'FREQ=DAILY;COUNT=501', 'FREQ=DAILY;INTERVAL=100', 'FREQ=DAILY;UNTIL=20261001',
                     'FREQ=DAILY;COUNT=2;UNTIL=20261101', 'FREQ=DAILY;BYHOUR=3', 'FREQ=WEEKLY;BYDAY=XX', 'FREQ=DAILY;FREQ=DAILY', 'nonsense',
                     'FREQ=WEEKLY;BYDAY=WE', 'FREQ=MONTHLY;BYMONTHDAY=14']:  # the last two do not include the Tuesday anchor
            with self.subTest(rule=rule), self.assertRaises(ValidationError):
                validate_rule(rule, anchor)

    def test_option_a_clock_changes(self):
        # Spring forward (2:00 to 3:00): a skipped 2:30 moves forward by the gap.
        self.assertEqual(wall_time(date(2026, 3, 8), time(2, 30), 'America/New_York'), (date(2026, 3, 8), time(3, 30)))
        # Fall back: a repeated 1:30 keeps the first (daylight) occurrence's wall time.
        self.assertEqual(wall_time(date(2026, 11, 1), time(1, 30), 'America/New_York'), (date(2026, 11, 1), time(1, 30)))
        self.assertEqual(wall_time(date(2026, 7, 1), time(2, 30), 'America/New_York'), (date(2026, 7, 1), time(2, 30)))

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class RecurringActivityTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.other = Household.objects.create(name='Other family')
        parent = get_user_model().objects.create_user('fixture@example.test')
        Membership.objects.create(user=parent, household=self.house)
        self.client.force_login(parent)
        self.child = FamilyMember.objects.create(household=self.house, name='Fixture child', role='child')

    def series_data(self, **changes):
        data = {'title': 'Practice', 'start_date': '2026-10-05', 'end_date': '2026-10-05', 'start_time': '17:00', 'end_time': '18:00',
                'participants': [str(self.child.pk)], 'version': 0, 'repeat': 'WEEKLY', 'interval': 1, 'weekdays': ['MO', 'WE'],
                'monthly_by': 'day', 'ends': 'until', 'until': '2026-11-30', 'count': ''}
        data.update(changes)
        return data

    def create_series(self, **changes):
        self.assertEqual(self.client.post('/plan/activity/new/', self.series_data(**changes)).status_code, 302)
        return Activity.objects.get(series__isnull=True, title=changes.get('title', 'Practice'))

    def titles_on(self, day):
        return sorted(e.title for e in household_events(self.house, day, day) if e.start_date <= day <= e.end_date)

    def test_create_series_and_show_occurrences_in_week_month_and_agenda(self):
        series = self.create_series()
        self.assertEqual(series.recurrence, 'FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261130')
        week = self.client.get('/?date=2026-10-14')
        days = [cell['date'] for cell in week.context['cells'] if any(e.title == 'Practice' for e in cell['events'])]
        self.assertEqual(days, [date(2026, 10, 12), date(2026, 10, 14)])
        self.assertContains(week, f'/activity/{series.pk}/?occurrence=2026-10-14')
        month = self.client.get('/?view=month&date=2026-11-01')
        self.assertEqual(sum(1 for cell in month.context['cells'] for e in cell['events'] if e.title == 'Practice'), 11)
        self.assertEqual(self.titles_on(date(2026, 12, 2)), [])
        detail = self.client.get(f'/activity/{series.pk}/?occurrence=2026-10-21')
        self.assertContains(detail, 'Wednesday, October 21, 2026')
        self.assertContains(detail, 'Every week on Monday, Wednesday, until Nov 30, 2026')
        self.assertEqual(self.client.get(f'/activity/{series.pk}/?occurrence=2026-10-22').status_code, 404)
        self.assertEqual(self.client.get(f'/activity/{series.pk}/?occurrence=bad').status_code, 404)

    def test_skipped_spring_forward_time_moves_forward_on_that_date_only(self):
        series = self.create_series(start_date='2026-03-01', end_date='2026-03-01', start_time='02:30', end_time='04:00',
                                    weekdays=['SU'], ends='count', count=3)
        events = {e.start_date: e for e in household_events(self.house, date(2026, 3, 1), date(2026, 3, 31))}
        self.assertEqual(sorted(events), [date(2026, 3, 1), date(2026, 3, 8), date(2026, 3, 15)])
        self.assertEqual((events[date(2026, 3, 8)].start_time, events[date(2026, 3, 8)].end_time), (time(3, 30), time(4, 0)))
        self.assertEqual(events[date(2026, 3, 15)].start_time, time(2, 30))
        self.assertEqual(series.start_time, time(2, 30))

    def test_multi_day_occurrences_overlap_the_window(self):
        self.create_series(title='Weekend camp', start_date='2026-10-02', end_date='2026-10-04', all_day='on', start_time='', end_time='',
                           weekdays=['FR'], ends='never', until='')
        self.assertEqual(self.titles_on(date(2026, 10, 11)), ['Weekend camp'])
        self.assertEqual(self.titles_on(date(2026, 10, 12)), [])
        week = self.client.get('/?date=2026-10-12')  # Monday after a weekend occurrence
        self.assertEqual([c['date'].day for c in week.context['cells'] if c['events']], [16, 17, 18])

    def test_edit_only_this_occurrence(self):
        series = self.create_series()
        data = self.series_data(title='Practice moved', start_date='2026-10-15', end_date='2026-10-15', start_time='18:00', end_time='19:30',
                                version=series.version, occurrence='2026-10-14', scope='one')
        response = self.client.post(f'/plan/activity/{series.pk}/edit/', data)
        override = Activity.objects.get(series=series)
        self.assertRedirects(response, f'/activity/{override.pk}/', fetch_redirect_response=False)
        self.assertEqual((override.occurrence_date, override.start_date, override.start_time, override.recurrence), (date(2026, 10, 14), date(2026, 10, 15), time(18), ''))
        self.assertEqual(list(override.participants.all()), [self.child])
        series.refresh_from_db()
        self.assertEqual((series.recurrence_exdates, series.title, series.version), (['2026-10-14'], 'Practice', 2))
        self.assertEqual(self.titles_on(date(2026, 10, 14)), [])
        self.assertEqual(self.titles_on(date(2026, 10, 15)), ['Practice moved'])
        self.assertEqual(self.titles_on(date(2026, 10, 21)), ['Practice'])
        # The changed date is no longer an occurrence of the series; replaying the edit conflicts.
        self.assertEqual(self.client.post(f'/plan/activity/{series.pk}/edit/', dict(data, version=2)).status_code, 404)
        self.assertContains(self.client.get(f'/plan/activity/{override.pk}/edit/'), 'changed occurrence')

    def test_edit_this_and_following_splits_the_series(self):
        series = self.create_series()
        Activity.objects.create(household=self.house, series=series, occurrence_date=date(2026, 11, 2), title='Later change',
                                start_date=date(2026, 11, 2), end_date=date(2026, 11, 2), all_day=True)
        Activity.objects.create(household=self.house, series=series, occurrence_date=date(2026, 10, 7), title='Earlier change',
                                start_date=date(2026, 10, 7), end_date=date(2026, 10, 7), all_day=True)
        data = self.series_data(title='Practice (new coach)', start_date='2026-10-19', end_date='2026-10-19', version=series.version,
                                occurrence='2026-10-19', scope='following')
        self.assertEqual(self.client.post(f'/plan/activity/{series.pk}/edit/', data).status_code, 302)
        series.refresh_from_db()
        self.assertEqual(series.recurrence, 'FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261014')
        new = Activity.objects.get(title='Practice (new coach)')
        self.assertEqual((new.start_date, new.series, new.recurrence), (date(2026, 10, 19), None, 'FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261130'))
        self.assertEqual(list(series.overrides.values_list('title', flat=True)), ['Earlier change'])
        self.assertEqual(self.titles_on(date(2026, 10, 14)), ['Practice'])
        self.assertEqual(self.titles_on(date(2026, 10, 19)), ['Practice (new coach)'])
        self.assertEqual(self.titles_on(date(2026, 11, 2)), ['Practice (new coach)'])

    def test_edit_all_from_an_occurrence_shifts_the_series(self):
        series = self.create_series()
        Activity.objects.create(household=self.house, series=series, occurrence_date=date(2026, 10, 26), title='Changed',
                                start_date=date(2026, 10, 26), end_date=date(2026, 10, 26), all_day=True)
        series.recurrence_exdates = ['2026-10-12', '2026-10-26']
        series.save()
        data = self.series_data(title='Practice B', start_date='2026-10-15', end_date='2026-10-15', weekdays=['TU', 'TH'],
                                version=series.version, occurrence='2026-10-14', scope='all')
        self.assertEqual(self.client.post(f'/plan/activity/{series.pk}/edit/', data).status_code, 302)
        series.refresh_from_db()
        self.assertEqual((series.title, series.start_date, series.recurrence), ('Practice B', date(2026, 10, 6), 'FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261130'))
        self.assertEqual(series.recurrence_exdates, ['2026-10-13', '2026-10-27'])
        self.assertEqual(series.overrides.get().occurrence_date, date(2026, 10, 27))
        self.assertEqual(Activity.objects.count(), 2)

    def test_first_date_must_match_the_pattern_and_all_edits_realign(self):
        response = self.client.post('/plan/activity/new/', self.series_data(start_date='2026-10-05', end_date='2026-10-05', weekdays=['WE']))
        self.assertContains(response, 'The first date must match the repeat pattern')
        series = self.create_series()
        data = self.series_data(start_date='2026-10-14', end_date='2026-10-14', weekdays=['TU'], version=series.version, occurrence='2026-10-14', scope='all')
        self.assertEqual(self.client.post(f'/plan/activity/{series.pk}/edit/', data).status_code, 302)
        series.refresh_from_db()
        self.assertEqual((series.start_date, series.recurrence), (date(2026, 10, 6), 'FREQ=WEEKLY;BYDAY=TU;UNTIL=20261130'))
        self.assertEqual(self.titles_on(date(2026, 10, 5)), [])
        self.assertEqual(self.titles_on(date(2026, 10, 6)), ['Practice'])

    def test_following_edit_with_a_new_pattern_starts_on_its_first_match(self):
        series = self.create_series()
        data = self.series_data(start_date='2026-10-21', end_date='2026-10-21', weekdays=['TU'], version=series.version, occurrence='2026-10-21', scope='following')
        self.assertEqual(self.client.post(f'/plan/activity/{series.pk}/edit/', data).status_code, 302)
        new = Activity.objects.exclude(pk=series.pk).get()
        self.assertEqual((new.start_date, new.end_date), (date(2026, 10, 27), date(2026, 10, 27)))
        self.assertEqual(self.titles_on(date(2026, 10, 21)), [])
        self.assertEqual(self.titles_on(date(2026, 10, 19)), ['Practice'])

    def test_stale_occurrence_edit_conflicts(self):
        series = self.create_series()
        Activity.objects.filter(pk=series.pk).update(version=5)
        data = self.series_data(version=1, occurrence='2026-10-14', scope='one')
        self.assertEqual(self.client.post(f'/plan/activity/{series.pk}/edit/', data).status_code, 409)
        self.assertFalse(Activity.objects.filter(series=series).exists())

    def test_delete_one_following_and_all(self):
        series = self.create_series()
        self.client.post(f'/plan/activity/{series.pk}/remove/', {'version': 1, 'occurrence': '2026-10-14', 'scope': 'one'})
        series.refresh_from_db()
        self.assertEqual(series.recurrence_exdates, ['2026-10-14'])
        self.assertEqual(self.titles_on(date(2026, 10, 14)), [])
        self.assertEqual(self.titles_on(date(2026, 10, 19)), ['Practice'])
        self.client.post(f'/plan/activity/{series.pk}/remove/', {'version': 2, 'occurrence': '2026-10-21', 'scope': 'following'})
        series.refresh_from_db()
        self.assertEqual(series.recurrence, 'FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261019')
        self.assertEqual(self.titles_on(date(2026, 10, 21)), [])
        self.assertContains(self.client.get(f'/plan/activity/{series.pk}/remove/?occurrence=2026-10-19'), 'This and following occurrences')
        self.client.post(f'/plan/activity/{series.pk}/remove/', {'version': 3, 'occurrence': '2026-10-19', 'scope': 'all'})
        self.assertFalse(Activity.objects.exists())

    def test_one_off_activity_and_quick_add_are_unchanged(self):
        data = self.series_data(repeat='')
        self.client.post('/plan/activity/new/', data)
        self.assertEqual(Activity.objects.get().recurrence, '')
        self.client.post('/', {'quick_kind': 'activity', 'activity-title': 'Quick', 'activity-start_date': '2026-10-20', 'activity-start_time': '09:00', 'activity-end_time': '10:00', 'activity-version': 0})
        self.assertEqual(Activity.objects.get(title='Quick').recurrence, '')
        self.assertContains(self.client.get('/plan/activity/new/'), 'Does not repeat')

    def test_repeat_form_validation(self):
        response = self.client.post('/plan/activity/new/', self.series_data(ends='until', until=''))
        self.assertContains(response, 'Choose the last date.')
        response = self.client.post('/plan/activity/new/', self.series_data(ends='until', until='2026-10-01'))
        self.assertContains(response, 'cannot be before the first date')
        response = self.client.post('/plan/activity/new/', self.series_data(interval=0))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Activity.objects.exists())

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class RecurringTaskTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        parent = get_user_model().objects.create_user('fixture@example.test')
        Membership.objects.create(user=parent, household=self.house)
        self.client.force_login(parent)

    def create_task(self, **changes):
        data = {'title': 'Take out recycling', 'due_date': '2026-10-15', 'due_time': '19:00', 'version': 0, 'repeat': 'WEEKLY',
                'interval': 1, 'weekdays': ['TH'], 'monthly_by': 'day', 'ends': 'never'}
        data.update(changes)
        self.assertEqual(self.client.post('/plan/task/new/', data).status_code, 302)
        return Task.objects.get(due_date=data['due_date'])

    def test_completing_creates_the_next_task_once(self):
        task = self.create_task()
        self.assertEqual((task.recurrence, task.recurrence_start), ('FREQ=WEEKLY;BYDAY=TH', date(2026, 10, 15)))
        self.assertIsNotNone(task.series_key)
        self.client.post(f'/tasks/{task.pk}/complete/', {'version': 1})
        following = Task.objects.get(due_date=date(2026, 10, 22))
        self.assertEqual((following.title, following.due_time, following.series_key, following.completed_at), (task.title, time(19), task.series_key, None))
        self.client.post(f'/tasks/{task.pk}/complete/', {'version': 2})  # reopen
        self.client.post(f'/tasks/{task.pk}/complete/', {'version': 3})  # complete again
        self.assertEqual(Task.objects.count(), 2)
        self.assertContains(self.client.get('/tasks/'), '⟳ Repeats')

    def test_series_end_and_skip_or_stop_on_delete(self):
        task = self.create_task(ends='count', count=2)
        self.client.post(f'/plan/task/{task.pk}/remove/', {'version': 1, 'task_scope': 'skip'})
        following = Task.objects.get()
        self.assertEqual(following.due_date, date(2026, 10, 22))
        self.client.post(f'/tasks/{following.pk}/complete/', {'version': 1})
        self.assertEqual(Task.objects.count(), 1)  # COUNT=2 reached; no third task
        other = self.create_task(title='Water plants', due_date='2026-10-16', weekdays=['FR'])
        self.client.post(f'/plan/task/{other.pk}/remove/', {'version': 1, 'task_scope': 'stop'})
        self.assertFalse(Task.objects.filter(title='Water plants').exists())

    def test_repeating_task_requires_a_due_date_and_quick_add_does_not_repeat(self):
        response = self.client.post('/plan/task/new/', {'title': 'No date', 'version': 0, 'repeat': 'DAILY', 'interval': 1, 'ends': 'never'})
        self.assertContains(response, 'Choose a date for the first occurrence.')
        self.client.post('/tasks/', {'quick_kind': 'task', 'task-title': 'Quick', 'task-due_date': '2026-10-15', 'task-version': 0})
        self.assertEqual(Task.objects.get(title='Quick').recurrence, '')

    def test_changing_the_rule_starts_a_new_series(self):
        task = self.create_task()
        key = task.series_key
        data = {'title': task.title, 'due_date': '2026-10-15', 'due_time': '19:00', 'version': 1, 'repeat': 'DAILY', 'interval': 1, 'ends': 'never', 'monthly_by': 'day'}
        self.client.post(f'/plan/task/{task.pk}/edit/', data)
        task.refresh_from_db()
        self.assertNotEqual(task.series_key, key)
        self.client.post(f'/plan/task/{task.pk}/edit/', dict(data, version=2, repeat=''))
        task.refresh_from_db()
        self.assertEqual((task.recurrence, task.series_key, task.recurrence_start), ('', None, None))

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class RecurrenceRecoveryTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.other = Household.objects.create(name='Other family')
        self.parent = get_user_model().objects.create_user('fixture@example.test')
        self.outsider = get_user_model().objects.create_user('outsider@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        Membership.objects.create(user=self.outsider, household=self.other)
        self.series = Activity.objects.create(household=self.house, title='Practice', start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
                                              all_day=True, recurrence='FREQ=WEEKLY;BYDAY=MO', recurrence_exdates=['2026-10-12', '2026-10-19'])
        Activity.objects.create(household=self.house, title='Practice moved', series=self.series, occurrence_date=date(2026, 10, 19),
                                start_date=date(2026, 10, 20), end_date=date(2026, 10, 20), all_day=True)
        Task.objects.create(household=self.house, title='Recycling', due_date=date(2026, 10, 15), recurrence='FREQ=WEEKLY;BYDAY=TH',
                            recurrence_start=date(2026, 10, 8), series_key='5b0c5f8e-58a4-4b1a-9c3e-2f6f3c8a1b11')

    def restore(self, user, data):
        self.client.force_login(user)
        upload = SimpleUploadedFile('household.json', json.dumps(data).encode(), content_type='application/json')
        self.assertEqual(self.client.post('/foundation/restore/', {'action': 'preview', 'backup': upload}).status_code, 200)
        self.assertEqual(self.client.post('/foundation/restore/', {'action': 'apply'}).status_code, 302)

    def test_series_overrides_and_repeating_tasks_round_trip_into_a_separate_household(self):
        exported = snapshot(self.house)
        self.assertEqual(exported['version'], 3)
        self.restore(self.outsider, exported)
        series = Activity.objects.get(household=self.other, series__isnull=True)
        override = Activity.objects.get(household=self.other, series__isnull=False)
        self.assertEqual((series.recurrence, series.recurrence_exdates), ('FREQ=WEEKLY;BYDAY=MO', ['2026-10-12', '2026-10-19']))
        self.assertEqual((override.series, override.occurrence_date), (series, date(2026, 10, 19)))
        self.assertNotEqual(series.pk, self.series.pk)
        task = Task.objects.get(household=self.other)
        self.assertEqual((task.recurrence, task.recurrence_start), ('FREQ=WEEKLY;BYDAY=TH', date(2026, 10, 8)))
        self.assertNotEqual(str(task.series_key), '5b0c5f8e-58a4-4b1a-9c3e-2f6f3c8a1b11')
        self.assertEqual(sorted(e.start_date for e in household_events(self.other, date(2026, 10, 1), date(2026, 10, 31))),
                         [date(2026, 10, 5), date(2026, 10, 20), date(2026, 10, 26)])

    def test_version_two_exports_still_restore(self):
        exported = snapshot(self.house)
        exported['version'] = 2
        exported['activities'] = [{k: v for k, v in row.items() if k not in ('recurrence', 'recurrence_exdates', 'series', 'occurrence_date')}
                                  for row in exported['activities'] if row['series'] is None]
        exported['tasks'] = [{k: v for k, v in row.items() if k not in ('recurrence', 'recurrence_start', 'series_key')} for row in exported['tasks']]
        self.restore(self.outsider, exported)
        self.assertEqual(Activity.objects.get(household=self.other).recurrence, '')
        self.assertEqual(Task.objects.get(household=self.other).recurrence, '')

    def test_invalid_recurrence_data_is_rejected(self):
        from copy import deepcopy
        from .recovery import validate_household
        good = snapshot(self.house)
        series_id = next(r['id'] for r in good['activities'] if r['series'] is None)
        override = next(i for i, r in enumerate(good['activities']) if r['series'])
        cases = [('activities', 0, 'recurrence', 'FREQ=SECONDLY'), ('activities', 0, 'recurrence_exdates', ['2026-13-01']),
                 ('activities', 0, 'recurrence_exdates', ['2026-10-12', '2026-10-12']), ('activities', override, 'series', '00000000-0000-0000-0000-000000000000'),
                 ('activities', override, 'occurrence_date', None), ('activities', override, 'recurrence', 'FREQ=DAILY'),
                 ('tasks', 0, 'recurrence_start', None), ('tasks', 0, 'series_key', 'not-a-uuid')]
        for collection, index, key, value in cases:
            bad = deepcopy(good)
            if collection == 'activities' and index == 0:
                index = next(i for i, r in enumerate(bad['activities']) if r['id'] == series_id)
            bad[collection][index][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                validate_household(bad)
        bad = deepcopy(good)
        bad['activities'].append(dict(bad['activities'][override], id='11111111-1111-1111-1111-111111111111'))
        with self.assertRaises(ValidationError):
            validate_household(bad)
