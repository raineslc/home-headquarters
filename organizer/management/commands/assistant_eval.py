from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from organizer.assistant_cases import CASES, FAMILY, resolve, run_checks
from organizer.assistant_service import AssistantUnavailable, propose
from organizer.models import FamilyMember, Household

class Rollback(Exception):
    pass

class Command(BaseCommand):
    help = ('Run the assistant regression cases against the real provider (uses API credit). '
            'A temporary household is created and rolled back; no organizer records are kept.')

    def add_arguments(self, parser):
        parser.add_argument('--case', action='append', help='Run only this case (repeatable).')

    def handle(self, case=None, **options):
        if not settings.OPENAI_API_KEY:
            raise CommandError('OPENAI_API_KEY is not configured.')
        cases = [c for c in CASES if not case or c.name in case]
        if not cases:
            raise CommandError('Unknown case. Choose from: ' + ', '.join(c.name for c in CASES))
        failures = 0
        try:
            with transaction.atomic():
                house = Household.objects.create(name='Assistant evaluation (temporary)', timezone='America/New_York')
                ids = {name: str(FamilyMember.objects.create(household=house, name=name, role=role).pk) for name, role in FAMILY}
                for item in cases:
                    try:
                        result = propose(house, item.turns(), resolve(item.drafts, ids), today=item.today)
                    except AssistantUnavailable as error:
                        failures += 1
                        self.stdout.write(f'FAIL {item.name}: {error}')
                        continue
                    outcomes = run_checks(item, result, ids)
                    failed = [text for text, passed in outcomes if not passed]
                    failures += bool(failed)
                    self.stdout.write(f'{"FAIL" if failed else "PASS"} {item.name} ({len(outcomes) - len(failed)}/{len(outcomes)} checks)')
                    for text in failed:
                        self.stdout.write(f'    - {text}')
                raise Rollback
        except Rollback:
            pass
        self.stdout.write(f'{len(cases) - failures}/{len(cases)} cases passed.')
        if failures:
            raise CommandError(f'{failures} case(s) failed.')
