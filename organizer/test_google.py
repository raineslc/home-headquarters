import hashlib
from datetime import date, timedelta
from unittest.mock import patch, Mock
from cryptography.fernet import Fernet
from django.test import TestCase, override_settings, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Household, Membership, GoogleConnection, GoogleCalendar, GoogleEvent, ParentInvitation
from . import google_service as google

@override_settings(SECURE_SSL_REDIRECT=False,
    GOOGLE_CLIENT_ID='fixture.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='fixture-only',
    GOOGLE_TOKEN_KEY=Fernet.generate_key().decode(),
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class GoogleTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture')
        self.parent = get_user_model().objects.create_user('one@example.test', email='one@example.test')
        self.partner = get_user_model().objects.create_user('two@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        Membership.objects.create(user=self.partner, household=self.house)
        self.connection = GoogleConnection.objects.create(household=self.house, owner=self.parent, subject='fixture', email='one@example.test', encrypted_refresh_token=google.cipher().encrypt(b'fixture-token').decode())
        self.calendar = GoogleCalendar.objects.create(connection=self.connection, external_id='fixture/calendar', name='Personal', access_role='owner', visibility='details')
        self.client.force_login(self.parent)

    def raw(self, **kwargs):
        return {'id': 'one', 'summary': 'Fixture meeting', 'start': {'dateTime': '2026-11-01T01:30:00-04:00'}, 'end': {'dateTime': '2026-11-01T01:30:00-05:00'}, **kwargs}

    def event(self):
        event = google.normalize_event(self.raw(), self.calendar, self.house.timezone)
        event.save()
        return event

    def test_merge_visibility_household_and_parent_ownership(self):
        event = self.event()
        self.assertContains(self.client.get('/?date=2026-11-01'), 'Fixture meeting')
        self.client.force_login(self.partner)
        self.assertContains(self.client.get(f'/connections/google/event/{event.pk}/'), 'Fixture meeting')
        self.assertEqual(self.client.post(f'/connections/google/{self.connection.pk}/disconnect/', {'version': 1}).status_code, 404)
        other = Household.objects.create(name='Other')
        Membership.objects.filter(user=self.partner).update(household=other)
        self.assertNotContains(self.client.get('/?date=2026-11-01'), 'Fixture meeting')
        self.assertEqual(self.client.get(f'/connections/google/event/{event.pk}/').status_code, 404)
        self.client.force_login(self.parent)
        self.assertEqual(self.client.post(f'/connections/google/{self.connection.pk}/choices/', {'version': 1, 'visibility_' + str(self.calendar.pk): 'busy'}).status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.title, 'Busy')
        self.assertEqual(event.location, '')
        self.assertEqual(self.client.post(f'/connections/google/{self.connection.pk}/choices/', {'version': 1}).status_code, 409)
        self.client.post(f'/connections/google/{self.connection.pk}/choices/', {'version': 2})
        self.assertFalse(GoogleEvent.objects.exists())

    def test_snapshot_retry_deletion_failure_and_concurrent_choices(self):
        with patch.object(google, 'paginated', return_value=[self.raw(), self.raw()]):
            google.sync_calendar(self.calendar, 'fixture')
            google.sync_calendar(self.calendar, 'fixture')
        self.assertEqual(GoogleEvent.objects.count(), 1)
        with patch.object(google, 'paginated', side_effect=google.GoogleUnavailable('Retry')):
            with self.assertRaises(google.GoogleUnavailable):
                google.sync_calendar(self.calendar, 'fixture')
        self.assertEqual(GoogleEvent.objects.count(), 1)
        with patch.object(google, 'paginated', return_value=[]):
            google.sync_calendar(self.calendar, 'fixture')
        self.assertFalse(GoogleEvent.objects.exists())
        def change(*args):
            GoogleConnection.objects.filter(pk=self.connection.pk).update(version=2)
            return [self.raw()]
        with patch.object(google, 'paginated', side_effect=change):
            with self.assertRaises(google.GoogleUnavailable):
                google.sync_calendar(self.calendar, 'fixture')
        self.assertFalse(GoogleEvent.objects.exists())

    def test_timezone_all_day_private_event_and_duplicate_calendar(self):
        event = google.normalize_event(self.raw(), self.calendar, self.house.timezone)
        self.assertEqual(event.start_date, date(2026, 11, 1))
        self.assertEqual(event.start_time.hour, 1)
        all_day = google.normalize_event(self.raw(start={'date': '2026-10-10'}, end={'date': '2026-10-13'}), self.calendar, self.house.timezone)
        self.assertEqual(all_day.end_date, date(2026, 10, 12))
        private = google.normalize_event(self.raw(visibility='private', location='Private address'), self.calendar, self.house.timezone)
        self.assertEqual((private.title, private.location, private.html_link), ('Busy', '', ''))
        event.save()
        second = GoogleConnection.objects.create(household=self.house, owner=self.partner, subject='second', email='two@example.test', encrypted_refresh_token='fixture')
        second_calendar = GoogleCalendar.objects.create(connection=second, external_id=self.calendar.external_id, name='Shared copy', access_role='reader', visibility='busy')
        google.normalize_event(self.raw(), second_calendar, self.house.timezone).save()
        merged = google.shared_events(self.house, date(2026, 11, 1), date(2026, 11, 1))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, 'Busy')

    def test_oauth_state_pkce_csrf_and_one_use(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.parent)
        self.assertEqual(csrf_client.post('/connections/google/connect/').status_code, 403)
        response = self.client.post('/connections/google/connect/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('code_challenge=', response.url)
        self.assertIn('code_challenge_method=S256', response.url)
        self.assertIn('calendar.events.readonly', response.url)
        with patch.object(google, 'flow') as flow:
            self.client.get('/connections/google/callback/?state=wrong&code=fixture')
            flow.assert_not_called()
        self.assertNotIn('google_oauth', self.client.session)
        self.assertNotIn('fixture-token', self.client.get('/connections/google/').content.decode())

    def test_oauth_connect_encrypts_and_starts_unshared(self):
        self.client.post('/connections/google/connect/')
        state = self.client.session['google_oauth']['state']
        credentials = Mock(granted_scopes=google.SCOPES, refresh_token='new-refresh-fixture', token='access-fixture')
        oauth = Mock(credentials=credentials)
        with patch.object(google, 'flow', return_value=oauth), patch.object(google, 'get_json', return_value={'sub': 'new-person', 'email': 'new@example.test', 'email_verified': True}), patch.object(google, 'paginated', return_value=[{'id': 'new-calendar', 'summary': 'New calendar', 'accessRole': 'owner'}]):
            response = self.client.get('/connections/google/callback/', {'state': state, 'code': 'fixture'})
        self.assertEqual(response.status_code, 302)
        connection = GoogleConnection.objects.get(subject='new-person')
        self.assertNotEqual(connection.encrypted_refresh_token, 'new-refresh-fixture')
        self.assertEqual(google.cipher().decrypt(connection.encrypted_refresh_token.encode()), b'new-refresh-fixture')
        self.assertEqual(connection.calendars.get().visibility, 'off')
        with patch.object(google, 'flow') as flow:
            self.client.get('/connections/google/callback/', {'state': state, 'code': 'fixture'})
            flow.assert_not_called()

    def test_permission_removed_and_disconnect_dont_touch_local_plans(self):
        self.event()
        with patch.object(google, 'paginated', return_value=[]):
            google.refresh_calendars(self.connection, 'fixture')
        self.assertFalse(GoogleEvent.objects.exists())
        self.connection.refresh_from_db()
        self.client.post(f'/connections/google/{self.connection.pk}/disconnect/', {'version': self.connection.version})
        self.assertFalse(GoogleConnection.objects.exists())

    def test_invitation_single_use_password_and_household(self):
        response = self.client.post('/settings/parents/', {'email': 'invited@example.test'})
        self.assertEqual(response.status_code, 200)
        link = response.context['invitation_link']
        self.assertTrue(link)
        invitation = ParentInvitation.objects.get()
        self.assertNotIn(invitation.token_hash, link)
        self.client.logout()
        self.client.get(link)
        self.assertEqual(self.client.get('/join/').status_code, 200)
        self.client.post('/join/', {'name': 'Partner', 'password': 'short', 'password_confirm': 'short'})
        self.assertFalse(get_user_model().objects.filter(username=invitation.email).exists())
        self.client.post('/join/', {'name': 'Partner', 'password': 'fixture-M7v2-long-passphrase', 'password_confirm': 'fixture-M7v2-long-passphrase'})
        user = get_user_model().objects.get(username=invitation.email)
        self.assertEqual(user.membership.household, self.house)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
        self.client.logout()
        self.client.get(link)
        self.assertEqual(self.client.get('/join/').status_code, 400)

    def test_join_form_submits_like_a_real_browser(self):
        # Regression (October 19): the join page sent Referrer-Policy: no-referrer, so browsers
        # submitted the form with "Origin: null" and the CSRF check answered 403 Forbidden.
        link = self.client.post('/settings/parents/', {'email': 'invited@example.test'}).context['invitation_link']
        browser = Client(enforce_csrf_checks=True)
        path = link[link.index('/join/'):]
        redirect = browser.get(path, secure=True)
        self.assertEqual(redirect['Referrer-Policy'], 'no-referrer')  # the address with the secret
        page = browser.get('/join/', secure=True)
        self.assertEqual(page.status_code, 200)
        self.assertNotEqual(page.get('Referrer-Policy'), 'no-referrer')
        token = page.context['csrf_token']
        data = {'csrfmiddlewaretoken': token, 'name': 'Partner', 'password': 'fixture-M7v2-long-passphrase', 'password_confirm': 'fixture-M7v2-long-passphrase'}
        self.assertEqual(browser.post('/join/', data, secure=True, HTTP_ORIGIN='null').status_code, 403)  # what no-referrer caused
        response = browser.post('/join/', data, secure=True, HTTP_ORIGIN='https://testserver')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username='invited@example.test').exists())

    def test_expired_invitation_and_cancelled_oauth(self):
        self.client.post('/connections/google/connect/')
        state = self.client.session['google_oauth']['state']
        with patch.object(google, 'flow') as flow:
            self.client.get('/connections/google/callback/', {'state': state, 'error': 'access_denied'})
            flow.assert_not_called()
        ParentInvitation.objects.create(household=self.house, created_by=self.parent, email='expired@example.test',
            token_hash=hashlib.sha256(b'expired-fixture').hexdigest(), expires_at=timezone.now() - timedelta(seconds=1))
        self.client.logout()
        self.client.get('/join/?invite=expired-fixture')
        self.assertEqual(self.client.get('/join/').status_code, 400)

    def test_tokens_from_another_sign_in_client_ask_to_reconnect(self):
        from google.auth.exceptions import RefreshError
        for code in ('invalid_grant', 'unauthorized_client', 'invalid_client'):
            GoogleConnection.objects.filter(pk=self.connection.pk).update(needs_reconnect=False)
            with self.subTest(code=code), patch('organizer.google_service.Credentials.refresh', side_effect=RefreshError(f'{code}: Unauthorized')):
                with self.assertRaises(google.ReconnectRequired):
                    google.access_token(self.connection)
            self.connection.refresh_from_db()
            self.assertTrue(self.connection.needs_reconnect)
        with patch('organizer.google_service.Credentials.refresh', side_effect=RefreshError('temporarily_unavailable')):
            with self.assertRaises(google.GoogleUnavailable) as raised:
                google.access_token(self.connection)
            self.assertNotIsInstance(raised.exception, google.ReconnectRequired)

    def test_failed_connect_logs_only_the_error_code(self):
        from oauthlib.oauth2.rfc6749.errors import InvalidClientError
        self.client.post('/connections/google/connect/')
        state = self.client.session['google_oauth']['state']
        oauth = Mock()
        oauth.fetch_token.side_effect = InvalidClientError(description='fixture-secret-detail')
        with patch.object(google, 'flow', return_value=oauth), self.assertLogs('organizer.google', level='WARNING') as logs:
            response = self.client.get('/connections/google/callback/', {'state': state, 'code': 'fixture-auth-code'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(logs.output, ['WARNING:organizer.google:Google connection failed: InvalidClientError invalid_client'])
        self.assertNotIn('fixture', ' '.join(logs.output))
