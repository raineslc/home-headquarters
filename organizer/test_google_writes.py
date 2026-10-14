import json
from datetime import date, time
from unittest.mock import Mock, patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from . import google_service as google
from . import google_writes
from .models import (Activity, FamilyCalendar, FamilyMember, GoogleCalendar, GoogleConnection, GoogleEvent,
                     GooglePendingDeletion, Household, Membership)

class FakeGoogle:
    """A minimal in-memory Google Calendar API: IDs, ETags, If-Match, duplicates and deletions."""
    def __init__(self):
        self.events, self.calls, self.fail = {}, [], []
        self.counter = 0

    def respond(self, status, body=None):
        response = Mock(status_code=status, content=json.dumps(body).encode() if body is not None else b'')
        response.json.return_value = body
        return response

    def __call__(self, method, url, headers=None, json=None, timeout=None, allow_redirects=None):
        self.calls.append((method, url, json))
        if self.fail:
            failure = self.fail.pop(0)
            if failure == 'network':
                import requests
                raise requests.ConnectionError('fixture outage')
            return self.respond(failure, {})
        path = url.split('/calendar/v3', 1)[1]
        if method == 'POST' and path == '/calendars':
            return self.respond(200, {'id': 'family-fixture@group.calendar.google.com', 'summary': json['summary']})
        identifier = path.rsplit('/events', 1)[1].lstrip('/') if '/events' in path else ''
        if method == 'POST':
            if json['id'] in self.events:
                return self.respond(409, {})
            self.counter += 1
            self.events[json['id']] = {'body': json, 'etag': f'"e{self.counter}"'}
            return self.respond(200, {'id': json['id'], 'etag': self.events[json['id']]['etag']})
        if identifier not in self.events:
            return self.respond(404, {})
        if method == 'DELETE':
            del self.events[identifier]
            return self.respond(204)
        if headers.get('If-Match') and headers['If-Match'] != self.events[identifier]['etag']:
            return self.respond(412, {})
        self.counter += 1
        self.events[identifier] = {'body': json, 'etag': f'"e{self.counter}"'}
        return self.respond(200, {'id': identifier, 'etag': self.events[identifier]['etag']})

    def edit_in_google(self, identifier):
        self.counter += 1
        self.events[identifier]['etag'] = f'"e{self.counter}"'

@override_settings(SECURE_SSL_REDIRECT=False, GOOGLE_CLIENT_ID='fixture.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='fixture-only',
    GOOGLE_TOKEN_KEY=Fernet.generate_key().decode(),
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class GoogleWriteTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture')
        self.other_house = Household.objects.create(name='Other')
        self.parent = get_user_model().objects.create_user('one@example.test', email='one@example.test')
        self.partner = get_user_model().objects.create_user('two@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        Membership.objects.create(user=self.partner, household=self.house)
        self.child = FamilyMember.objects.create(household=self.house, name='Logan', role='child')
        self.connection = GoogleConnection.objects.create(household=self.house, owner=self.parent, subject='fixture', email='one@example.test',
                                                          encrypted_refresh_token=google.cipher().encrypt(b'fixture-token').decode())
        self.client.force_login(self.parent)
        self.fake = FakeGoogle()
        patches = [patch('organizer.google_writes.requests.request', side_effect=self.fake),
                   patch.object(google, 'access_token', return_value='access-fixture')]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def post(self, *args, **kwargs):
        # Google writes run after the database commit; run those callbacks as a real request would.
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(*args, **kwargs)

    def setup_family(self):
        self.post(f'/connections/google/{self.connection.pk}/family/')
        state = self.client.session['google_oauth']['state']
        self.assertTrue(self.client.session['google_oauth']['write'])
        credentials = Mock(granted_scopes=google.SCOPES + [google.WRITE_SCOPE], refresh_token='refresh-with-write', token='access-fixture')
        with patch.object(google, 'flow', return_value=Mock(credentials=credentials)) as flow, \
             patch.object(google, 'get_json', return_value={'sub': 'fixture', 'email': 'one@example.test', 'email_verified': True}), \
             patch.object(google, 'paginated', return_value=[{'id': 'family-fixture@group.calendar.google.com', 'summary': 'Home Headquarters', 'accessRole': 'owner'}]):
            self.client.get('/connections/google/callback/', {'state': state, 'code': 'fixture'})
            self.assertTrue(flow.call_args.kwargs['write'])
        return FamilyCalendar.objects.get(household=self.house)

    def activity_data(self, **changes):
        data = {'title': 'Soccer', 'start_date': '2026-10-17', 'end_date': '2026-10-17', 'start_time': '09:00', 'end_time': '10:30',
                'participants': [str(self.child.pk)], 'location': 'Field 2', 'notes': 'Bring water', 'version': 0, 'google_sync': 'on',
                'repeat': '', 'interval': 1, 'monthly_by': 'day', 'ends': 'never'}
        data.update(changes)
        return data

    def test_read_only_until_a_parent_opts_in(self):
        self.assertNotContains(self.client.get('/plan/activity/new/'), 'Also add to the family Google calendar')
        response = self.post('/connections/google/connect/')
        self.assertIn('include_granted_scopes=true', response.url)
        self.assertNotIn('calendar.app.created', response.url)
        self.post('/plan/activity/new/', self.activity_data())
        self.assertFalse(Activity.objects.get().google_sync)
        self.assertEqual(self.fake.calls, [])
        page = self.client.get('/connections/google/')
        self.assertContains(page, 'Create the family calendar in one@example.test')
        response = self.post(f'/connections/google/{self.connection.pk}/family/')
        self.assertIn('calendar.app.created', response.url)
        self.assertIn('login_hint=one%40example.test', response.url)

    def test_setup_creates_app_calendar_and_writes_chosen_activities(self):
        family = self.setup_family()
        self.connection.refresh_from_db()
        self.assertTrue(self.connection.can_write)
        self.assertEqual(google.cipher().decrypt(self.connection.encrypted_refresh_token.encode()), b'refresh-with-write')
        self.assertEqual((family.calendar.external_id, family.calendar.visibility), ('family-fixture@group.calendar.google.com', 'off'))
        self.assertContains(self.client.get('/plan/activity/new/'), 'Also add to the family Google calendar')
        self.post('/plan/activity/new/', self.activity_data())
        activity = Activity.objects.get()
        self.assertEqual((activity.google_state, activity.google_event_id), ('synced', 'hhq' + activity.pk.hex))
        body = self.fake.events[activity.google_event_id]['body']
        self.assertEqual(body['start'], {'dateTime': '2026-10-17T09:00:00', 'timeZone': self.house.timezone})
        self.assertEqual((body['summary'], body['location']), ('Soccer', 'Field 2'))
        self.assertIn('Who: Logan', body['description'])
        # Editing updates the same Google event with the stored ETag.
        self.post(f'/plan/activity/{activity.pk}/edit/', self.activity_data(title='Soccer final', version=activity.version))
        self.assertEqual(len(self.fake.events), 1)
        self.assertEqual(self.fake.events[activity.google_event_id]['body']['summary'], 'Soccer final')
        self.assertEqual(self.fake.calls[-1][0], 'PUT')
        # Unticking removes the Google copy; an activity left unticked is never sent.
        activity.refresh_from_db()
        self.post(f'/plan/activity/{activity.pk}/edit/', self.activity_data(version=activity.version, google_sync=''))
        self.assertEqual(self.fake.events, {})
        self.post('/plan/activity/new/', self.activity_data(title='Private', google_sync=''))
        self.assertEqual(self.fake.events, {})

    def test_retry_after_outage_never_duplicates(self):
        self.setup_family()
        self.fake.fail = ['network']
        self.post('/plan/activity/new/', self.activity_data())
        activity = Activity.objects.get()
        self.assertEqual(activity.google_state, 'failed')
        self.assertContains(self.client.get(f'/activity/{activity.pk}/'), 'Retry Google update')
        # The first insert reached Google but the reply was lost: the retry must not add a second copy.
        self.fake.events['hhq' + activity.pk.hex] = {'body': {}, 'etag': '"lost"'}
        self.post(f'/activity/{activity.pk}/google/', {'action': 'retry'})
        activity.refresh_from_db()
        self.assertEqual((activity.google_state, len(self.fake.events)), ('synced', 1))
        self.assertEqual(self.fake.events[activity.google_event_id]['body']['summary'], 'Soccer')

    def test_changes_made_in_google_are_not_overwritten_without_a_choice(self):
        self.setup_family()
        self.post('/plan/activity/new/', self.activity_data())
        activity = Activity.objects.get()
        self.fake.edit_in_google(activity.google_event_id)
        self.post(f'/plan/activity/{activity.pk}/edit/', self.activity_data(title='App edit', version=activity.version))
        activity.refresh_from_db()
        self.assertEqual(activity.google_state, 'conflict')
        self.assertNotEqual(self.fake.events[activity.google_event_id]['body'].get('summary'), 'App edit')
        page = self.client.get(f'/activity/{activity.pk}/')
        self.assertContains(page, 'Use this version in Google')
        # Further edits stay local until a parent chooses.
        self.post(f'/plan/activity/{activity.pk}/edit/', self.activity_data(title='Second edit', version=activity.version))
        self.assertNotEqual(self.fake.events[activity.google_event_id]['body'].get('summary'), 'Second edit')
        self.post(f'/activity/{activity.pk}/google/', {'action': 'keep_app'})
        activity.refresh_from_db()
        self.assertEqual((activity.google_state, self.fake.events[activity.google_event_id]['body']['summary']), ('synced', 'Second edit'))

    def test_deleted_in_google_and_unlink(self):
        self.setup_family()
        self.post('/plan/activity/new/', self.activity_data())
        activity = Activity.objects.get()
        old_id = activity.google_event_id
        del self.fake.events[old_id]
        self.post(f'/plan/activity/{activity.pk}/edit/', self.activity_data(version=activity.version))
        activity.refresh_from_db()
        self.assertEqual(activity.google_state, 'removed')
        self.post(f'/activity/{activity.pk}/google/', {'action': 'recreate'})
        activity.refresh_from_db()
        self.assertEqual(activity.google_state, 'synced')
        self.assertNotEqual(activity.google_event_id, old_id)
        self.post(f'/activity/{activity.pk}/google/', {'action': 'unlink'})
        activity.refresh_from_db()
        self.assertEqual((activity.google_sync, activity.google_event_id), (False, ''))
        self.assertEqual(len(self.fake.events), 1)  # left in Google

    def test_deleting_activities_removes_google_copies_and_queues_failures(self):
        self.setup_family()
        self.post('/plan/activity/new/', self.activity_data())
        self.post('/plan/activity/new/', self.activity_data(title='Second'))
        first, second = Activity.objects.order_by('title')
        self.post(f'/plan/activity/{first.pk}/remove/', {'version': first.version})
        self.assertNotIn(first.google_event_id, self.fake.events)
        self.fake.fail = [503]
        self.post(f'/plan/activity/{second.pk}/remove/', {'version': second.version})
        self.assertEqual(GooglePendingDeletion.objects.get().event_id, second.google_event_id)
        self.assertContains(self.client.get('/connections/google/'), 'still to remove from Google')
        self.post('/connections/google/family/retry/')
        self.assertFalse(GooglePendingDeletion.objects.exists())
        self.assertEqual(self.fake.events, {})

    def test_repeating_series_exceptions_and_changed_occurrences(self):
        self.setup_family()
        data = self.activity_data(start_date='2026-10-05', end_date='2026-10-05', repeat='WEEKLY', weekdays=['MO'], ends='until', until='2026-11-30')
        self.post('/plan/activity/new/', data)
        series = Activity.objects.get()
        body = self.fake.events[series.google_event_id]['body']
        self.assertEqual(body['recurrence'], ['RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261201T045959Z'])
        change = self.activity_data(title='Soccer moved', start_date='2026-10-13', end_date='2026-10-13', version=series.version,
                                    occurrence='2026-10-12', scope='one')
        self.post(f'/plan/activity/{series.pk}/edit/', change)
        series.refresh_from_db()
        override = Activity.objects.get(series=series)
        self.assertEqual(self.fake.events[series.google_event_id]['body']['recurrence'][1], f'EXDATE;TZID={self.house.timezone}:20261012T090000')
        self.assertEqual(self.fake.events[override.google_event_id]['body']['summary'], 'Soccer moved')
        # Deleting the whole series removes it and its changed occurrence from Google.
        self.post(f'/plan/activity/{series.pk}/remove/', {'version': series.version})
        self.assertEqual(self.fake.events, {})

    def test_cached_copies_of_app_events_are_not_shown_twice(self):
        family = self.setup_family()
        self.post('/plan/activity/new/', self.activity_data())
        activity = Activity.objects.get()
        GoogleCalendar.objects.filter(pk=family.calendar.pk).update(visibility='details')
        for external in [activity.google_event_id, activity.google_event_id + '_20261017T130000Z', 'made-in-google']:
            GoogleEvent.objects.create(calendar=family.calendar, external_id=external, title='Soccer' if external != 'made-in-google' else 'Dentist',
                                       start_date=date(2026, 10, 17), end_date=date(2026, 10, 17), start_time=time(9), end_time=time(10, 30))
        titles = [event.title for event in google.shared_events(self.house, date(2026, 10, 17), date(2026, 10, 17))]
        self.assertEqual(titles, ['Dentist'])

    def test_permission_loss_restore_and_stop_leave_google_untouched(self):
        self.setup_family()
        self.post('/plan/activity/new/', self.activity_data())
        activity = Activity.objects.get()
        with patch.object(google, 'access_token', side_effect=google.WritePermissionLost('Permission removed.')):
            self.post(f'/plan/activity/{activity.pk}/edit/', self.activity_data(version=activity.version, title='Edited'))
        activity.refresh_from_db()
        self.assertEqual((activity.google_state, activity.google_error), ('failed', 'Permission removed.'))
        # Restoring a backup replaces local data but never deletes Google events.
        from .recovery import replace_household_data, snapshot
        calls = len(self.fake.calls)
        with self.captureOnCommitCallbacks(execute=True):
            replace_household_data(self.house, self.parent, snapshot(self.house))
        self.assertEqual(len(self.fake.calls), calls)
        self.assertFalse(GooglePendingDeletion.objects.exists())
        self.post('/connections/google/family/stop/')
        self.assertFalse(FamilyCalendar.objects.exists())
        self.assertEqual(len(self.fake.events), 1)
        self.assertNotContains(self.client.get('/plan/activity/new/'), 'Also add to the family Google calendar')

    def test_other_households_and_parents_cannot_use_google_actions(self):
        self.setup_family()
        self.post('/plan/activity/new/', self.activity_data())
        activity = Activity.objects.get()
        outsider = get_user_model().objects.create_user('three@example.test')
        Membership.objects.create(user=outsider, household=self.other_house)
        self.client.force_login(outsider)
        self.assertEqual(self.post(f'/activity/{activity.pk}/google/', {'action': 'unlink'}).status_code, 404)
        self.client.force_login(self.partner)
        self.assertEqual(self.post(f'/connections/google/{self.connection.pk}/family/').status_code, 404)
        self.assertContains(self.client.get('/connections/google/'), 'one@example.test’s Google account')
