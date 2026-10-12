from datetime import timedelta
from django.core.management import BaseCommand
from django.db import connection, transaction
from django.utils import timezone
from organizer.models import JobRun, RateLimit

class Command(BaseCommand):
    help = 'Foundation scheduler heartbeat. Does not send reminders or synchronize calendars yet.'
    def handle(self, **options):
        now = timezone.now()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [47290003])
                if not cursor.fetchone()[0]:
                    self.stdout.write('Another job run is active.')
                    return
            run, created = JobRun.objects.get_or_create(key='heartbeat:' + now.strftime('%Y%m%d%H%M'))
            if not created and run.status == 'complete':
                self.stdout.write('This minute has already completed.')
                return
            RateLimit.objects.filter(window_start__lt=now - timedelta(days=1)).delete()
            JobRun.objects.filter(completed_at__lt=now - timedelta(days=30)).delete()
            run.status = 'complete'
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'completed_at'])
        self.stdout.write('Foundation heartbeat completed; reminder delivery is not implemented.')
