import json
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from organizer.models import Household
from organizer.recovery import snapshot

class Command(BaseCommand):
    help = 'Write a complete version 2 household export (no accounts, tokens or secrets) to a JSON file.'

    def add_arguments(self, parser):
        parser.add_argument('output', help='Path of the JSON file to create. Store it privately.')
        parser.add_argument('--household', help='Household ID; required when more than one household exists.')

    def handle(self, output, household=None, **options):
        households = Household.objects.filter(pk=household) if household else Household.objects.all()
        if households.count() != 1:
            raise CommandError('Choose exactly one household with --household.')
        with transaction.atomic():
            locked = households.select_for_update().get()
            data = snapshot(locked)
        try:
            with open(output, 'x', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
        except FileExistsError:
            raise CommandError('That file already exists; choose a new path.')
        self.stdout.write(f'Exported {len(data["members"])} members, {len(data["activities"])} activities and {len(data["tasks"])} tasks.')
