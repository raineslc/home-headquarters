import json
from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from . import webpush
from .models import Activity, FamilyMember, Household, Membership, PushSubscription, ReminderDelivery, Task
from .reminders import due_reminders, send_due

KEY = ec.generate_private_key(ec.SECP256R1()).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
ZONE = ZoneInfo('America/New_York')
ENDPOINT = 'https://fcm.googleapis.com/fcm/send/fixture-device-1'
DEVICE_KEYS = {'p256dh': 'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4', 'auth': 'BTBZMqHH6r4Tts7J_aSIgg'}

def moment(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=ZONE)

class WebPushTests(TestCase):
    def test_encryption_matches_rfc_8291_example(self):
        server = ec.derive_private_key(int.from_bytes(webpush.unb64('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'), 'big'), ec.SECP256R1())
        body = webpush.encrypt(b'When I grow up, I want to be a watermelon', DEVICE_KEYS['p256dh'], DEVICE_KEYS['auth'],
                               salt=webpush.unb64('DGv6ra1nlYgDCS1FRnbzlw'), server_key=server)
        self.assertEqual(webpush.b64(body), 'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6Tlz'
                         'AC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN')

    @override_settings(WEB_PUSH_PRIVATE_KEY=KEY, WEB_PUSH_CONTACT='https://hhq.example.test')
    def test_vapid_token_is_signed_for_the_push_service(self):
        key = webpush.private_key()
        header = webpush.vapid_header(ENDPOINT, key)
        token, public = header[len('vapid t='):].split(', k=')
        self.assertEqual(public, webpush.public_key())
        head, claims, signature = token.split('.')
        self.assertEqual(json.loads(webpush.unb64(claims))['aud'], 'https://fcm.googleapis.com')
        raw = webpush.unb64(signature)
        key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big')),
                                f'{head}.{claims}'.encode(), ec.ECDSA(hashes.SHA256()))

    def test_only_known_push_services_are_accepted(self):
        for endpoint in (ENDPOINT, 'https://updates.push.services.mozilla.com/wpush/v2/x', 'https://web.push.apple.com/abc',
                         'https://wns2-by3p.notify.windows.com/w/?token=x'):
            self.assertTrue(webpush.allowed_endpoint(endpoint), endpoint)
        for endpoint in ('http://fcm.googleapis.com/x', 'https://fcm.googleapis.com.evil.test/x', 'https://127.0.0.1/x',
                         'https://evilpush.apple.com/x', 'https://fcm.googleapis.com:8443/x', 'https://u@fcm.googleapis.com/x', None, 'x' * 1001):
            self.assertFalse(webpush.allowed_endpoint(endpoint), endpoint)

@override_settings(SECURE_SSL_REDIRECT=False, WEB_PUSH_PRIVATE_KEY=KEY, JOB_INVOKER_EMAIL='hhq-scheduler@example.test', APP_HOSTNAME='hhq.example.test',
                   STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ReminderTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.other = Household.objects.create(name='Other family')
        users = get_user_model().objects
        self.parent = users.create_user('fixture@example.test')
        self.outsider = users.create_user('outsider@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        Membership.objects.create(user=self.outsider, household=self.other)
        self.client.force_login(self.parent)
        self.child = FamilyMember.objects.create(household=self.house, name='Sam', role='child')
        self.party = Activity.objects.create(household=self.house, title='Party', start_date=date(2026, 10, 17), end_date=date(2026, 10, 17),
                                             start_time=time(14), end_time=time(16), location='Fixture hall', reminder_minutes=60)
        self.party.participants.set([self.child])

    def device(self, household=None, endpoint=ENDPOINT, user=None):
        return PushSubscription.objects.create(household=household or self.house, user=user or self.parent, endpoint=endpoint, **DEVICE_KEYS)

    def test_due_window_and_message(self):
        self.assertEqual(due_reminders(self.house, moment(17, 12, 50)), [])
        found = due_reminders(self.house, moment(17, 12, 55))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['title'], 'Party')
        self.assertEqual(found[0]['body'], 'Starts today at 2:00 PM · Fixture hall · Sam')
        self.assertEqual(found[0]['url'], f'/activity/{self.party.pk}/')
        # Missed while the scheduler was paused, but the party hasn't started: still sent.
        self.assertEqual(len(due_reminders(self.house, moment(17, 13, 50))), 1)
        self.assertEqual(due_reminders(self.house, moment(17, 14, 1)), [])
        self.assertEqual(due_reminders(self.other, moment(17, 12, 55)), [])

    def test_repeating_activity_and_tasks(self):
        swim = Activity.objects.create(household=self.house, title='Swim', start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
                                       start_time=time(17), end_time=time(18), recurrence='FREQ=WEEKLY;BYDAY=MO', recurrence_exdates=['2026-10-26'],
                                       reminder_minutes=1440)
        found = due_reminders(self.house, moment(18, 17))
        self.assertEqual([(r['title'], r['url'], r['body']) for r in found], [('Swim', f'/activity/{swim.pk}/?occurrence=2026-10-19', 'Starts tomorrow at 5:00 PM')])
        self.assertEqual(due_reminders(self.house, moment(25, 17)), [])  # skipped date
        Task.objects.create(household=self.house, title='Sign form', due_date=date(2026, 10, 20), due_time=time(18), reminder_minutes=30, assignee=self.child)
        Task.objects.create(household=self.house, title='Pay fees', due_date=date(2026, 10, 20), reminder_minutes=60)
        Task.objects.create(household=self.house, title='Done already', due_date=date(2026, 10, 20), due_time=time(18), reminder_minutes=30,
                            completed_at=moment(19, 9))
        self.assertEqual([(r['title'], r['body']) for r in due_reminders(self.house, moment(20, 7))], [('Pay fees', 'Due today')])
        self.assertEqual([(r['title'], r['body']) for r in due_reminders(self.house, moment(20, 17, 30))], [('Sign form', 'Due today at 6:00 PM · Sam')])

    def test_each_reminder_is_sent_once_per_device_and_again_when_moved(self):
        phone, laptop = self.device(), self.device(endpoint=ENDPOINT + '-laptop')
        self.device(household=self.other, endpoint=ENDPOINT + '-other', user=self.outsider)
        with patch('organizer.webpush.send') as send:
            self.assertEqual(send_due(moment(17, 12, 55))['sent'], 2)
            self.assertEqual({call.args[0] for call in send.call_args_list}, {phone, laptop})
            self.assertEqual(send.call_args.args[1]['title'], 'Party')
            self.assertEqual(send_due(moment(17, 13, 10))['sent'], 0)
            Activity.objects.filter(pk=self.party.pk).update(start_time=time(15))
            self.assertEqual(send_due(moment(17, 13, 55))['sent'], 2)
            self.party.delete()
            self.assertEqual(send_due(moment(17, 14, 55))['sent'], 0)
        phone.refresh_from_db()
        self.assertIsNotNone(phone.last_sent_at)

    def test_failures_retry_then_stop_and_gone_devices_are_removed(self):
        phone, old = self.device(), self.device(endpoint=ENDPOINT + '-old')
        def flaky(subscription, message):
            if subscription == old:
                raise webpush.PushError('gone', gone=True)
            raise webpush.PushError('Push service answered 503.')
        with patch('organizer.webpush.send', side_effect=flaky):
            for minute in (50, 55, 58, 59):
                send_due(moment(17, 13, minute))
        self.assertFalse(PushSubscription.objects.filter(pk=old.pk).exists())
        delivery = ReminderDelivery.objects.get(subscription=phone)
        self.assertEqual((delivery.attempts, delivery.sent_at, delivery.last_error), (3, None, 'Push service answered 503.'))

    def test_scheduler_endpoint_requires_a_google_identity_token(self):
        self.client.logout()
        self.assertEqual(self.client.post('/jobs/reminders/').status_code, 403)
        claims = {'email': 'hhq-scheduler@example.test', 'email_verified': True}
        with patch('google.oauth2.id_token.verify_oauth2_token', return_value=claims) as verify, patch('organizer.reminders.send_due', return_value={'sent': 1, 'failed': 0, 'busy': False}):
            response = self.client.post('/jobs/reminders/', HTTP_AUTHORIZATION='Bearer signed-token')
        self.assertEqual(response.json()['sent'], 1)
        self.assertEqual(verify.call_args.kwargs['audience'], 'https://hhq.example.test/jobs/reminders/')
        with patch('google.oauth2.id_token.verify_oauth2_token', return_value=dict(claims, email='someone@example.test')):
            self.assertEqual(self.client.post('/jobs/reminders/', HTTP_AUTHORIZATION='Bearer signed-token').status_code, 403)
        with patch('google.oauth2.id_token.verify_oauth2_token', side_effect=ValueError('bad token')):
            self.assertEqual(self.client.post('/jobs/reminders/', HTTP_AUTHORIZATION='Bearer forged').status_code, 403)

    def test_devices_subscribe_test_and_unsubscribe_within_the_household(self):
        post = lambda url, data: self.client.post(url, json.dumps(data), content_type='application/json')
        self.assertEqual(post('/push/subscribe/', {'endpoint': 'https://attacker.example.test/x', 'keys': DEVICE_KEYS}).status_code, 400)
        self.assertEqual(post('/push/subscribe/', {'endpoint': ENDPOINT, 'keys': {'p256dh': 'short', 'auth': 'x'}}).status_code, 400)
        self.assertEqual(post('/push/subscribe/', {'endpoint': ENDPOINT, 'keys': DEVICE_KEYS}).json()['devices'], 1)
        self.assertEqual(post('/push/subscribe/', {'endpoint': ENDPOINT, 'keys': DEVICE_KEYS}).json()['devices'], 1)
        device = PushSubscription.objects.get()
        self.assertEqual(device.household, self.house)
        with patch('organizer.webpush.send') as send:
            self.assertEqual(post('/push/test/', {'endpoint': ENDPOINT}).status_code, 200)
        self.assertEqual(send.call_args.args[1]['body'], 'Reminders are on for this device.')
        page = self.client.get('/settings/')
        self.assertContains(page, 'Phone reminders')
        self.assertContains(page, f'data-push-key="{webpush.public_key()}"')
        self.client.force_login(self.outsider)
        post('/push/unsubscribe/', {'endpoint': ENDPOINT})
        self.client.post(f'/push/devices/{device.pk}/remove/')
        self.assertEqual(post('/push/test/', {'endpoint': ENDPOINT}).status_code, 404)
        self.assertTrue(PushSubscription.objects.filter(pk=device.pk).exists())
        self.client.force_login(self.parent)
        post('/push/unsubscribe/', {'endpoint': ENDPOINT})
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(WEB_PUSH_PRIVATE_KEY='')
    def test_not_set_up_on_the_server(self):
        self.assertContains(self.client.get('/settings/'), 'Not set up on the server yet.')
        response = self.client.post('/push/subscribe/', json.dumps({'endpoint': ENDPOINT, 'keys': DEVICE_KEYS}), content_type='application/json')
        self.assertEqual(response.status_code, 503)

    def test_service_worker_shows_notifications(self):
        body = self.client.get('/sw.js').content.decode()
        self.assertIn("addEventListener('push'", body)
        self.assertIn("addEventListener('notificationclick'", body)
