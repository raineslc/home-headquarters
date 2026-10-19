import json
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from . import backups
from .models import BackupRun, Household, Membership, Task
from .recovery import validate_household

ZONE = ZoneInfo('America/New_York')

def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=ZONE)  # October 25, 2026 is a Sunday

@override_settings(SECURE_SSL_REDIRECT=False, BACKUP_BUCKET='fixture-hhq-backups', JOB_INVOKER_EMAIL='hhq-scheduler@example.test', APP_HOSTNAME='hhq.example.test',
                   STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class BackupTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.parent = get_user_model().objects.create_user('fixture@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        Task.objects.create(household=self.house, title='Buy a gift')
        self.client.force_login(self.parent)

    def saved(self, when):
        run = BackupRun.objects.create(household=self.house, object_name='x', size=10, finished_at=when)
        BackupRun.objects.filter(pk=run.pk).update(created_at=when)

    def test_schedule_sunday_evening_catch_up_and_retry_wait(self):
        self.assertTrue(backups.is_due(self.house, at(20, 10)))  # never backed up
        self.saved(at(20, 10))
        self.assertFalse(backups.is_due(self.house, at(24, 22)))  # Saturday evening
        self.assertFalse(backups.is_due(self.house, at(25, 20, 45)))  # Sunday before 9 PM
        self.assertTrue(backups.is_due(self.house, at(25, 21)))
        self.saved(at(25, 21))
        self.assertFalse(backups.is_due(self.house, at(25, 22, 30)))  # already done tonight
        self.assertFalse(backups.is_due(self.house, at(28, 12)))
        BackupRun.objects.all().delete()
        self.saved(at(17, 21))
        self.assertTrue(backups.is_due(self.house, at(25, 21)))
        self.assertTrue(backups.is_due(self.house, at(25, 22)))  # Sunday missed? catch up: over 8 days old
        BackupRun.objects.create(household=self.house, object_name='y', error='Cloud Storage answered 503.')
        self.assertFalse(backups.is_due(self.house, timezone_now()))  # a failed attempt waits an hour

    def test_saves_a_valid_export_without_overwriting(self):
        with patch.object(backups, 'upload') as upload:
            run = backups.run(self.house, at(25, 21, 5))
        name, body = upload.call_args.args
        self.assertEqual(name, f'{self.house.pk}/home-headquarters-2026-10-25-2105.json')
        data = json.loads(body)
        validate_household(data)
        self.assertEqual([task['title'] for task in data['tasks']], ['Buy a gift'])
        self.assertEqual((run.error, run.size), ('', len(body)))
        self.assertIsNotNone(run.finished_at)

    def test_upload_uses_create_only_request(self):
        class Reply:
            status_code = 200
        with patch('google.auth.default', return_value=(object(), 'project')), \
                patch('google.auth.transport.requests.AuthorizedSession.post', return_value=Reply()) as post:
            backups.upload('house/file.json', b'{}')
        self.assertEqual(post.call_args.kwargs['params'], {'uploadType': 'media', 'name': 'house/file.json', 'ifGenerationMatch': '0'})
        self.assertIn('/b/fixture-hhq-backups/o', post.call_args.args[0])
        Reply.status_code = 403
        with patch('google.auth.default', return_value=(object(), 'project')), \
                patch('google.auth.transport.requests.AuthorizedSession.post', return_value=Reply()):
            with self.assertRaises(backups.BackupError):
                backups.upload('house/file.json', b'{}')

    def test_failures_are_recorded_and_shown(self):
        with patch.object(backups, 'upload', side_effect=backups.BackupError('Cloud Storage answered 403.')):
            self.assertEqual(backups.backup_due(), {'saved': 0, 'failed': 1})
        page = self.client.get('/foundation/')
        self.assertContains(page, 'The last attempt failed: Cloud Storage answered 403.')
        self.assertContains(self.client.get('/settings/'), 'last attempt failed')

    def test_back_up_now_and_scheduler_run(self):
        with patch.object(backups, 'upload'):
            response = self.client.post('/foundation/backup/')
        self.assertRedirects(response, '/foundation/', fetch_redirect_response=False)
        self.assertContains(self.client.get('/foundation/'), 'Last saved')
        claims = {'email': 'hhq-scheduler@example.test', 'email_verified': True}
        with patch('google.oauth2.id_token.verify_oauth2_token', return_value=claims), \
                patch('organizer.reminders.send_due', return_value={'sent': 0, 'failed': 0, 'busy': False}), \
                patch('organizer.reminders.google_due', return_value={'synced': 0, 'failed': 0, 'retried': 0}), patch.object(backups, 'upload'):
            result = self.client.post('/jobs/reminders/', HTTP_AUTHORIZATION='Bearer signed').json()
        self.assertEqual(result['backup'], {'saved': 0, 'failed': 0})  # just backed up

    @override_settings(BACKUP_BUCKET='')
    def test_off_until_set_up(self):
        with patch.object(backups, 'upload') as upload:
            self.assertEqual(backups.backup_due(), {'saved': 0, 'failed': 0})
            self.client.post('/foundation/backup/')
        upload.assert_not_called()
        self.assertContains(self.client.get('/foundation/'), 'Not set up on the server yet')

def timezone_now():
    from django.utils import timezone
    return timezone.now()
