from datetime import date, timedelta
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from . import google_service as google
from . import google_writes
from .models import Activity, GoogleCalendar, GoogleConnection, GoogleEvent, GooglePendingDeletion, Household, Membership

@override_settings(SECURE_SSL_REDIRECT=False,
    GOOGLE_CLIENT_ID='fixture.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='fixture-only',
    GOOGLE_TOKEN_KEY=Fernet.generate_key().decode(), JOB_INVOKER_EMAIL='hhq-scheduler@example.test', APP_HOSTNAME='hhq.example.test',
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ScheduledGoogleSyncTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture')
        self.parent = get_user_model().objects.create_user('one@example.test', email='one@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        self.connection = GoogleConnection.objects.create(household=self.house, owner=self.parent, subject='fixture', email='one@example.test',
                                                          encrypted_refresh_token=google.cipher().encrypt(b'fixture-token').decode())
        self.shared = GoogleCalendar.objects.create(connection=self.connection, external_id='shared', name='Personal', access_role='owner', visibility='details')
        self.hidden = GoogleCalendar.objects.create(connection=self.connection, external_id='hidden', name='Work', access_role='owner', visibility='off')
        self.client.force_login(self.parent)

    def raw(self):
        return {'id': 'one', 'summary': 'Dentist', 'start': {'dateTime': '2026-11-02T09:00:00-05:00'}, 'end': {'dateTime': '2026-11-02T10:00:00-05:00'}}

    def test_shared_calendars_refresh_without_changing_the_parents_form_version(self):
        with patch.object(google, 'access_token', return_value='token'), patch.object(google, 'paginated', return_value=[self.raw()]) as fetch:
            self.assertEqual(google.sync_due(), {'synced': 1, 'failed': 0})
            self.assertEqual(fetch.call_count, 1)  # the unshared calendar is never read
            self.assertEqual(google.sync_due(), {'synced': 0, 'failed': 0})  # just synced
            later = timezone.now() + timedelta(minutes=15)
            self.assertEqual(google.sync_due(later)['synced'], 1)
        self.assertEqual(list(GoogleEvent.objects.values_list('title', 'calendar')), [('Dentist', self.shared.pk)])
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.version, 1)

    def test_expired_sign_in_is_skipped_and_shown_on_the_overview(self):
        def expire(connection, write=False):
            GoogleConnection.objects.filter(pk=connection.pk).update(needs_reconnect=True)
            raise google.ReconnectRequired('Google access expired. Connect this account again.')
        with patch.object(google, 'access_token', side_effect=expire):
            self.assertEqual(google.sync_due(), {'synced': 0, 'failed': 1})
            self.assertEqual(google.sync_due(), {'synced': 0, 'failed': 0})  # waits for the parent to reconnect
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.sync_error, 'Google access expired. Connect this account again.')
        self.assertContains(self.client.get('/'), 'Your Google Calendar connection has expired')
        GoogleConnection.objects.update(needs_reconnect=False)
        self.assertNotContains(self.client.get('/'), 'Your Google Calendar connection has expired')

    def test_failed_family_calendar_updates_retry_but_conflicts_wait(self):
        failed = Activity.objects.create(household=self.house, title='Swim', start_date=date(2026, 11, 2), end_date=date(2026, 11, 2),
                                         google_sync=True, google_state='failed')
        Activity.objects.filter(pk=failed.pk).update(google_state='failed')
        conflict = Activity.objects.create(household=self.house, title='Recital', start_date=date(2026, 11, 3), end_date=date(2026, 11, 3), google_sync=True)
        Activity.objects.filter(pk=conflict.pk).update(google_state='conflict')
        GooglePendingDeletion.objects.create(calendar=self.shared, event_id='gone', title='Old')
        with patch.object(google_writes, 'push', return_value='synced') as push, patch.object(google_writes, 'remove_remote', return_value=True) as remove:
            self.assertEqual(google_writes.retry_failed(), 2)
        self.assertEqual([call.args[0].pk for call in push.call_args_list], [failed.pk])
        self.assertEqual(remove.call_args.args[1:], ('gone', 'Old'))

    def test_scheduler_run_syncs_after_reminders_and_survives_google_errors(self):
        claims = {'email': 'hhq-scheduler@example.test', 'email_verified': True}
        with patch('google.oauth2.id_token.verify_oauth2_token', return_value=claims), \
                patch('organizer.reminders.send_due', return_value={'sent': 0, 'failed': 0, 'busy': False}), \
                patch.object(google, 'sync_due', return_value={'synced': 1, 'failed': 0}), \
                patch.object(google_writes, 'retry_failed', return_value=0):
            response = self.client.post('/jobs/reminders/', HTTP_AUTHORIZATION='Bearer signed')
        self.assertEqual(response.json()['google'], {'synced': 1, 'failed': 0, 'retried': 0})
        with patch('google.oauth2.id_token.verify_oauth2_token', return_value=claims), \
                patch('organizer.reminders.send_due', return_value={'sent': 2, 'failed': 0, 'busy': False}), \
                patch.object(google, 'sync_due', side_effect=RuntimeError('unexpected')):
            response = self.client.post('/jobs/reminders/', HTTP_AUTHORIZATION='Bearer signed')
        self.assertEqual((response.status_code, response.json()['sent'], response.json()['google']['failed']), (200, 2, 1))

    def test_connections_page_explains_automatic_refresh(self):
        self.assertContains(self.client.get('/connections/google/'), 'refresh automatically every 15 minutes')
