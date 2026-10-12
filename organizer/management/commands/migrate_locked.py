from django.core.management import BaseCommand, call_command
from django.db import connection

class Command(BaseCommand):
    help = 'Apply versioned migrations with a PostgreSQL deployment lock.'
    def handle(self, **options):
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(%s)', [47290002])
            try:
                call_command('migrate', interactive=False)
            finally:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [47290002])
