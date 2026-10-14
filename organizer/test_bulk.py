from datetime import date, timedelta
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from .models import Activity, FamilyMember, Household, Membership

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class BulkActivityTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.other = Household.objects.create(name='Other family')
        parent = get_user_model().objects.create_user('fixture@example.test')
        Membership.objects.create(user=parent, household=self.house)
        self.client.force_login(parent)
        self.child = FamilyMember.objects.create(household=self.house, name='Fixture child', role='child')
        self.foreign = FamilyMember.objects.create(household=self.other, name='Private child', role='child')

    def data(self, action, dates, **changes):
        values = {'action': action, 'title': 'Soccer game', 'start_time': '09:00', 'end_time': '10:30', 'participants': [str(self.child.pk)],
                  'location': 'Fixture field', 'notes': '', 'reminder_minutes': '', 'version': 0, 'batch': '6f1d3a2e-4b5c-4d6e-8f70-112233445566',
                  'from': '2026-10-01', 'to': '2026-12-31', 'dates': dates}
        values.update(changes)
        return values

    def test_page_defaults_to_six_weeks_from_today(self):
        response = self.client.get('/plan/activity/bulk/')
        today = timezone.localdate(timezone=ZoneInfo(self.house.timezone))
        self.assertEqual((response.context['start'], response.context['end']), (today, today + timedelta(days=41)))
        days = [cell['date'] for week in response.context['grid'] for cell in week if cell['in_range']]
        self.assertEqual(len(days), 42)
        self.assertContains(response, 'Select every Mon in range')
        self.assertContains(self.client.get('/plan/activity/new/'), 'Add on several dates instead')
        long = self.client.get('/plan/activity/bulk/?from=2026-01-01&to=2027-12-31')
        self.assertEqual(long.context['end'], date(2026, 4, 30))

    def test_review_then_create_all_dates_once(self):
        dates = ['2026-10-24', '2026-10-17', '2026-10-31', '2026-10-17']
        Activity.objects.create(household=self.house, title='Existing party', start_date=date(2026, 10, 24), end_date=date(2026, 10, 24), all_day=True)
        review = self.client.post('/plan/activity/bulk/', self.data('review', dates))
        self.assertContains(review, 'Review 3 dates')
        self.assertContains(review, 'Also on this date: Existing party')
        self.assertEqual([row['date'] for row in review.context['rows']], [date(2026, 10, 17), date(2026, 10, 24), date(2026, 10, 31)])
        self.assertEqual(Activity.objects.filter(title='Soccer game').count(), 0)
        version = Household.objects.get(pk=self.house.pk).version
        response = self.client.post('/plan/activity/bulk/', self.data('create', dates))
        self.assertRedirects(response, '/?date=2026-10-17&view=month', fetch_redirect_response=False)
        created = Activity.objects.filter(title='Soccer game').order_by('start_date')
        self.assertEqual([a.start_date for a in created], [date(2026, 10, 17), date(2026, 10, 24), date(2026, 10, 31)])
        for item in created:
            self.assertEqual((item.end_date, item.location, item.timezone, item.recurrence, str(item.batch)),
                             (item.start_date, 'Fixture field', self.house.timezone, '', '6f1d3a2e-4b5c-4d6e-8f70-112233445566'))
            self.assertEqual(list(item.participants.all()), [self.child])
        self.assertEqual(Household.objects.get(pk=self.house.pk).version, version + 1)
        # Submitting the same batch again adds nothing.
        self.client.post('/plan/activity/bulk/', self.data('create', dates))
        self.assertEqual(Activity.objects.filter(title='Soccer game').count(), 3)

    def test_a_problem_on_any_date_blocks_every_date(self):
        dates = ['2026-03-01', '2026-03-08', '2026-03-15']  # March 8 has no 2:30 AM
        values = self.data('review', dates, start_time='02:30', end_time='03:45', **{'from': '2026-03-01', 'to': '2026-03-31'})
        review = self.client.post('/plan/activity/bulk/', values)
        self.assertFalse(review.context['ready'])
        self.assertEqual([bool(row['problems']) for row in review.context['rows']], [False, True, False])
        self.assertContains(review, 'Nothing has been added')
        self.assertNotContains(review, 'value="create"')
        response = self.client.post('/plan/activity/bulk/', dict(values, action='create'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Activity.objects.exists())

    def test_invalid_dates_and_details_are_rejected(self):
        cases = [([], 'Choose at least one date.'), (['2027-02-01'], 'Choose dates within the range shown.'), (['not-a-date'], 'not valid'),
                 ([(date(2026, 10, 1) + timedelta(days=i)).isoformat() for i in range(61)], 'Choose up to 60 dates')]
        for dates, message in cases:
            with self.subTest(message=message):
                self.assertContains(self.client.post('/plan/activity/bulk/', self.data('create', dates)), message)
        self.assertContains(self.client.post('/plan/activity/bulk/', self.data('create', ['2026-10-17'], title='')), 'This field is required')
        self.assertContains(self.client.post('/plan/activity/bulk/', self.data('create', ['2026-10-17'], end_time='08:00')), 'The end must be after the start.')
        response = self.client.post('/plan/activity/bulk/', self.data('create', ['2026-10-17'], participants=[str(self.foreign.pk)]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Activity.objects.exists())

    def test_all_day_activities_and_changing_the_range_keep_details(self):
        values = self.data('create', ['2026-11-26', '2026-11-27'], all_day='on', start_time='', end_time='', title='Holiday')
        self.client.post('/plan/activity/bulk/', values)
        self.assertEqual(sorted(Activity.objects.filter(all_day=True).values_list('start_date', flat=True)), [date(2026, 11, 26), date(2026, 11, 27)])
        response = self.client.post('/plan/activity/bulk/', self.data('range', ['2026-10-17', '2026-12-20'], title='Kept title', **{'from': '2026-10-01', 'to': '2026-11-30'}))
        self.assertContains(response, 'value="Kept title"')
        chosen = [cell['date'] for week in response.context['grid'] for cell in week if cell['checked']]
        self.assertEqual(chosen, [date(2026, 10, 17)])
        self.assertEqual(response.context['chosen_count'], 1)
