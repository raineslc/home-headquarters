import json
from copy import deepcopy
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, SimpleTestCase, override_settings
from .models import Household, Membership, SetupRecord, RecoveryPoint, JobRun
from .recovery import snapshot, validate_snapshot

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class FoundationTests(TestCase):
    def setUp(self):
        self.parent = get_user_model().objects.create_user('parent@example.test', password='Test-only-passphrase-482!')
        self.other = get_user_model().objects.create_user('other@example.test', password='Test-only-passphrase-391!')
        self.house = Household.objects.create(name='Test household')
        self.other_house = Household.objects.create(name='Isolated household')
        Membership.objects.create(user=self.parent, household=self.house)
        Membership.objects.create(user=self.other, household=self.other_house)
        self.client.force_login(self.parent)

    def test_anonymous_data_operations_require_sign_in(self):
        anonymous = Client()
        for path in ['/', '/foundation/export/', '/foundation/restore/', '/foundation/recovery/']:
            self.assertEqual(anonymous.get(path).status_code, 302)
        self.assertEqual(anonymous.post('/foundation/records/', {'title': 'Unapproved'}).status_code, 302)
        self.assertFalse(SetupRecord.objects.exists())

    def test_real_password_auth_and_persisted_record(self):
        self.client.logout()
        response = self.client.post('/sign-in/', {'username': 'PARENT@example.test', 'password': 'Test-only-passphrase-482!'})
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.client.post('/foundation/records/', {'title': 'Record survives a second request', 'household_id': str(self.other_house.id)})
        self.assertContains(self.client.get('/'), 'Record survives a second request')
        self.assertEqual(SetupRecord.objects.get().household_id, self.house.id)

    def test_households_cannot_read_each_other(self):
        SetupRecord.objects.create(household=self.other_house, title='Private other household note')
        self.assertNotContains(self.client.get('/'), 'Private other household note')
        self.assertEqual(self.client.get('/foundation/export/').json()['records'], [])
        point = RecoveryPoint.objects.create(household=self.other_house, created_by=self.other, payload=snapshot(self.other_house))
        self.assertEqual(self.client.get(f'/foundation/recovery/{point.id}/').status_code, 404)

    def test_inactive_membership_is_denied(self):
        Membership.objects.filter(user=self.parent).update(active=False)
        self.assertEqual(self.client.get('/foundation/export/').status_code, 403)
        self.assertEqual(self.client.post('/foundation/records/', {'title': 'Denied'}).status_code, 403)

    def test_csrf_is_enforced(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.parent)
        self.assertEqual(browser.post('/foundation/records/', {'title': 'Denied'}).status_code, 403)

    def preview(self, data):
        upload = SimpleUploadedFile('household.json', json.dumps(data).encode(), content_type='application/json')
        return self.client.post('/foundation/restore/', {'action': 'preview', 'backup': upload})

    def test_restore_validates_before_write_and_saves_recovery_point(self):
        SetupRecord.objects.create(household=self.house, title='Original')
        data = snapshot(self.house)
        data['records'] = [{'title': 'Restored'}]
        self.assertEqual(self.preview(data).status_code, 200)
        self.assertEqual(SetupRecord.objects.get().title, 'Original')
        self.client.post('/foundation/restore/', {'action': 'apply'})
        self.assertEqual(SetupRecord.objects.get().title, 'Restored')
        point = RecoveryPoint.objects.get(household=self.house)
        self.assertEqual(point.payload['records'], [{'title': 'Original'}])
        self.assertNotIn('password', json.dumps(point.payload))
        # Replaying apply cannot overwrite again without another preview.
        self.assertEqual(self.client.post('/foundation/restore/', {'action': 'apply'}).status_code, 400)

    def test_restore_rejects_a_stale_preview(self):
        self.preview(snapshot(self.house))
        self.client.post('/foundation/records/', {'title': 'New parent edit'})
        response = self.client.post('/foundation/restore/', {'action': 'apply'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(SetupRecord.objects.get().title, 'New parent edit')
        self.assertFalse(RecoveryPoint.objects.exists())

    def test_export_restores_to_a_separate_household_without_accounts_or_secrets(self):
        SetupRecord.objects.create(household=self.house, title='Recovery fixture')
        exported = self.client.get('/foundation/export/').json()
        self.client.force_login(self.other)
        self.preview(exported)
        self.client.post('/foundation/restore/', {'action': 'apply'})
        self.assertEqual(SetupRecord.objects.filter(household=self.other_house).get().title, 'Recovery fixture')
        self.other_house.refresh_from_db()
        self.assertEqual(self.other_house.name, 'Isolated household')
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_scheduler_retry_is_idempotent(self):
        call_command('run_jobs')
        call_command('run_jobs')
        self.assertEqual(JobRun.objects.filter(status='complete').count(), 1)

    @override_settings(OWNER_EMAIL='new@example.test', BOOTSTRAP_TOKEN='test-only-private-bootstrap-token')
    def test_bootstrap_requires_secret_and_closes_after_setup(self):
        anonymous = Client()
        values = {'email': 'new@example.test', 'name': 'New Parent', 'household': 'New household',
                  'password': 'Long-unique-test-password-967!', 'password_confirm': 'Long-unique-test-password-967!', 'token': 'wrong'}
        anonymous.post('/setup/', values)
        self.assertFalse(get_user_model().objects.filter(username='new@example.test').exists())
        values['token'] = 'test-only-private-bootstrap-token'
        self.assertEqual(anonymous.post('/setup/', values).status_code, 302)
        self.assertEqual(Client().get('/setup/').status_code, 403)

class ExportValidationTests(SimpleTestCase):
    def test_invalid_exports_are_rejected(self):
        good = {'format': 'home-headquarters', 'version': 1, 'scope': 'foundation', 'exported_at': '2026-10-12T12:00:00+00:00',
                'household': {'name': 'Fixture', 'timezone': 'America/New_York'}, 'records': [{'title': 'Fixture note'}]}
        self.assertEqual(validate_snapshot(good), good['records'])
        for key, value in [('version', True), ('version', 99), ('records', [{'title': ''}]), ('records', [{'title': 'ok', 'token': 'no'}]), ('exported_at', None)]:
            bad = deepcopy(good)
            bad[key] = value
            with self.assertRaises(ValidationError):
                validate_snapshot(bad)
