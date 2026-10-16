from django.core.management import BaseCommand
from organizer.reminders import send_due

class Command(BaseCommand):
    help = 'Send due phone reminders once (the hosted app runs this from Cloud Scheduler).'
    def handle(self, **options):
        result = send_due()
        if result['busy']:
            self.stdout.write('Another reminder run is active.')
        else:
            self.stdout.write(f"Reminders: {result['sent']} sent, {result['failed']} failed.")
