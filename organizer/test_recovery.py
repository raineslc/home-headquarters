import json
import os
import tempfile
import uuid
from copy import deepcopy
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from .models import (Activity, AssistantPlan, AssistantSuggestion, ChecklistItem, FamilyMember, GoogleConnection, Household,
                     ListTemplate, LunchPlan, Membership, ParentInvitation, PendingRestore, RecoveryPoint, SetupRecord, Task)
from .recovery import snapshot, validate_household

def canonical(data):
    """Replace generated identifiers with names so two households' exports can be compared."""
    members = {row['id']: row['name'] for row in data['members']}
    activities = {row['id']: row['title'] for row in data['activities']}
    tasks = {row['id']: row['title'] for row in data['tasks']}
    result = deepcopy({k: v for k, v in data.items() if k not in ('exported_at', 'household')})
    for row in result['members']:
        row.pop('id')
    for row in result['activities']:
        row.pop('id')
        row['participants'] = sorted(members[x] for x in row['participants'])
        row['series'] = activities.get(row['series'])
    for row in result['tasks']:
        row.pop('id')
        row['assignee'], row['activity'] = members.get(row['assignee']), activities.get(row['activity'])
        row['series_key'] = bool(row['series_key'])
    for row in result['lunches']:
        row['child'] = members[row['child']]
    for plan in result['assistant_plans']:
        plan.pop('id')
        plan.pop('created_by')
        for item in plan['suggestions']:
            item.pop('decided_by')
            item['activity'], item['task'] = activities.get(item['activity']), tasks.get(item['task'])
            payload = item['payload']
            if 'participants' in payload:
                payload['participants'] = sorted(members[x] for x in payload['participants'])
            if payload.get('assignee'):
                payload['assignee'] = members[payload['assignee']]
    for name in ('members', 'activities', 'tasks', 'lunches', 'list_templates'):
        result[name].sort(key=lambda row: json.dumps(row, sort_keys=True))
    return result

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class HouseholdRecoveryTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.parent = users.create_user('parent@example.test', password='Test-only-passphrase-482!')
        self.second = users.create_user('second@example.test', password='Test-only-passphrase-517!')
        self.outsider = users.create_user('outsider@example.test', password='Test-only-passphrase-391!')
        self.house = Household.objects.create(name='Fixture household')
        self.other = Household.objects.create(name='Isolated household', timezone='America/Chicago')
        Membership.objects.create(user=self.parent, household=self.house)
        Membership.objects.create(user=self.second, household=self.house)
        Membership.objects.create(user=self.outsider, household=self.other)
        self.populate()
        self.client.force_login(self.parent)

    def populate(self):
        house = self.house
        self.adult = FamilyMember.objects.create(household=house, name='Fixture Parent', role='parent', color='blue')
        self.child = FamilyMember.objects.create(household=house, name='Fixture Child', role='child', color='orange')
        self.archived = FamilyMember.objects.create(household=house, name='Former Child', role='child', archived=True)
        self.party = Activity.objects.create(household=house, title='Party', start_date='2026-10-17', end_date='2026-10-17',
                                             start_time='14:00', end_time='16:00', location='Fixture hall', notes='Bring a card',
                                             reminder_minutes=60, version=3)
        self.party.participants.set([self.adult, self.child])
        trip = Activity.objects.create(household=house, title='Trip', start_date='2026-11-01', end_date='2026-11-03', all_day=True)
        trip.participants.set([self.archived])
        self.gift = Task.objects.create(household=house, title='Buy a gift', assignee=self.adult, activity=self.party, due_date='2026-10-16',
                                        due_time='18:00', high_priority=True, reminder_minutes=1440, search_prompt='Gift for a 7 year old',
                                        search_questions='Budget?', completed_at=timezone.now())
        Task.objects.create(household=house, title='Household chore', notes='No assignee or activity')
        ChecklistItem.objects.create(household=house, activity=self.party, text='Card', position=0, done_at=timezone.now())
        ChecklistItem.objects.create(household=house, activity=self.party, text='Sunscreen', position=1, done_dates=['2026-10-17'])
        ChecklistItem.objects.create(household=house, task=self.gift, text='Wrapping paper', position=0)
        ListTemplate.objects.create(household=house, name='Swim bag', items=['Towel', 'Goggles'])
        LunchPlan.objects.create(household=house, child=self.child, date='2026-10-14', choice='pack')
        LunchPlan.objects.create(household=house, child=self.archived, date='2026-10-15', choice='school')
        SetupRecord.objects.create(household=house, title='Deployment note')
        plan = AssistantPlan.objects.create(household=house, created_by=self.second, request_key=uuid.uuid4(), title='Birthday party',
                                            messages=[{'role': 'user', 'content': 'Birthday party Saturday'}], reply='Draft ready',
                                            questions=['Whose birthday is it?'], status='ready', revision=1)
        AssistantSuggestion.objects.create(plan=plan, revision=1, kind='event', position=0, status='approved', activity=self.party,
                                           payload={'title': 'Party', 'participants': [str(self.child.pk)]}, decided_by=self.second,
                                           decided_at=timezone.now())
        AssistantSuggestion.objects.create(plan=plan, revision=1, kind='task', position=1, status='approved', task=self.gift,
                                           payload={'title': 'Buy a gift', 'assignee': str(self.adult.pk)}, decided_by=self.parent,
                                           decided_at=timezone.now())
        AssistantSuggestion.objects.create(plan=plan, revision=1, kind='task', position=2, status='pending',
                                           payload={'title': 'Confirm address', 'assignee': str(self.child.pk)})
        AssistantSuggestion.objects.create(plan=plan, revision=0, kind='task', position=0, status='superseded', payload={'title': 'Old draft'})
        GoogleConnection.objects.create(household=house, owner=self.parent, subject='fixture-subject', email='parent@example.test',
                                        encrypted_refresh_token='fixture-encrypted-refresh-token')
        ParentInvitation.objects.create(household=house, created_by=self.parent, token_hash='f' * 64, email='invitee@example.test',
                                        expires_at=timezone.now() + timedelta(days=1))

    def preview(self, data, client=None):
        upload = SimpleUploadedFile('household.json', json.dumps(data).encode(), content_type='application/json')
        return (client or self.client).post('/foundation/restore/', {'action': 'preview', 'backup': upload})

    def apply(self, client=None):
        return (client or self.client).post('/foundation/restore/', {'action': 'apply'})

    def test_export_contains_all_organizer_data_and_no_secrets(self):
        response = self.client.get('/foundation/export/')
        self.assertIn('home-headquarters-household-v2-', response['Content-Disposition'])
        data = response.json()
        self.assertEqual({k: len(data[k]) for k in ('notes', 'members', 'activities', 'tasks', 'lunches', 'assistant_plans')},
                         {'notes': 1, 'members': 3, 'activities': 2, 'tasks': 2, 'lunches': 2, 'assistant_plans': 1})
        self.assertEqual(len(data['assistant_plans'][0]['suggestions']), 4)
        text = json.dumps(data)
        for secret in ('fixture-encrypted-refresh-token', 'fixture-subject', 'f' * 64, 'invitee@example.test', 'password', 'pbkdf2'):
            self.assertNotIn(secret, text)
        self.assertEqual(validate_household(data), data)

    def test_recovery_drill_into_a_separate_household(self):
        exported = self.client.get('/foundation/export/').json()
        before = canonical(snapshot(self.house))
        outsider = Client()
        outsider.force_login(self.outsider)
        preview = self.preview(exported, outsider)
        self.assertContains(preview, '3 family members')
        self.assertContains(preview, '1 saved list and 3 checklist items')
        self.assertContains(preview, 'Time zone differs')
        self.assertEqual(self.apply(outsider).status_code, 302)
        restored = snapshot(self.other)
        self.assertEqual(canonical(restored), before)
        # New identifiers: nothing in the restored household points back to the source household.
        source_ids = {str(x) for x in FamilyMember.objects.filter(household=self.house).values_list('pk', flat=True)}
        source_ids |= {str(x) for x in Activity.objects.filter(household=self.house).values_list('pk', flat=True)}
        text = json.dumps(restored)
        self.assertFalse([x for x in source_ids if x in text])
        # Source household and the target's identity, accounts and connections are untouched.
        self.assertEqual(canonical(snapshot(self.house)), before)
        self.other.refresh_from_db()
        self.assertEqual((self.other.name, self.other.timezone), ('Isolated household', 'America/Chicago'))
        self.assertFalse(GoogleConnection.objects.filter(household=self.other).exists())
        # Authors who are not parents of the target household fall back to the restoring parent.
        plan = AssistantPlan.objects.get(household=self.other)
        self.assertEqual(plan.created_by, self.outsider)
        self.assertFalse(plan.suggestions.exclude(decided_by=None).exists())
        self.assertEqual(plan.created_at.isoformat(), exported['assistant_plans'][0]['created_at'])
        self.assertNotEqual(plan.request_key, AssistantPlan.objects.get(household=self.house).request_key)

    def test_restore_into_same_household_and_undo_with_recovery_point(self):
        original = canonical(snapshot(self.house))
        exported = self.client.get('/foundation/export/').json()
        Task.objects.create(household=self.house, title='Added after export')
        self.archived.delete()
        changed = canonical(snapshot(self.house))
        self.house.refresh_from_db()
        self.preview(exported)
        self.assertEqual(Task.objects.filter(household=self.house, title='Added after export').count(), 1)
        self.assertEqual(self.apply().status_code, 302)
        self.assertEqual(canonical(snapshot(self.house)), original)
        plan = AssistantPlan.objects.get(household=self.house)
        self.assertEqual(plan.created_by, self.second)
        self.assertEqual(set(plan.suggestions.exclude(decided_by=None).values_list('decided_by__username', flat=True)),
                         {'parent@example.test', 'second@example.test'})
        pending = plan.suggestions.get(status='pending')
        self.assertEqual(FamilyMember.objects.get(pk=pending.payload['assignee']).name, 'Fixture Child')
        self.assertTrue(GoogleConnection.objects.filter(household=self.house).exists())
        self.assertTrue(ParentInvitation.objects.filter(household=self.house).exists())
        point = RecoveryPoint.objects.get(household=self.house)
        self.assertEqual(canonical(point.payload), changed)
        # The recovery copy is itself a restorable export.
        self.preview(self.client.get(f'/foundation/recovery/{point.pk}/').json())
        self.assertEqual(self.apply().status_code, 302)
        self.assertEqual(canonical(snapshot(self.house)), changed)
        self.assertEqual(RecoveryPoint.objects.filter(household=self.house).count(), 2)

    def test_invalid_exports_are_rejected_before_any_change(self):
        good = snapshot(self.house)
        member, child = good['members'][0]['id'], next(r['id'] for r in good['members'] if r['role'] == 'child')
        parent_member = next(r['id'] for r in good['members'] if r['role'] == 'parent')
        party = next(i for i, r in enumerate(good['activities']) if r['title'] == 'Party')
        gift = next(i for i, r in enumerate(good['tasks']) if r['title'] == 'Buy a gift')
        def mutate(path, value):
            def change(data):
                target = data
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
            return change
        cases = [
            mutate(['activities', 0, 'participants'], [str(uuid.uuid4())]),
            mutate(['activities', 0, 'participants'], [member, member]),
            mutate(['activities', 0, 'end_date'], '2026-01-01'),
            mutate(['activities', 0, 'timezone'], 'Mars/Base'),
            mutate(['activities', 0, 'reminder_minutes'], True),
            mutate(['activities', 0, 'start_time'], '25:00'),
            mutate(['tasks', 0, 'assignee'], str(uuid.uuid4())),
            mutate(['tasks', 0, 'completed_at'], '2026-10-01T10:00:00'),
            mutate(['lunches', 0, 'child'], parent_member),
            mutate(['lunches', 0, 'choice'], 'pizza'),
            mutate(['lunches', 1], {'child': child, 'date': '2026-10-14', 'choice': 'school'}),
            mutate(['members', 1, 'id'], member),
            mutate(['members', 0, 'role'], 'admin'),
            mutate(['members', 0, 'token'], 'unexpected'),
            mutate(['assistant_plans', 0, 'suggestions', 0, 'task'], str(uuid.uuid4())),
            mutate(['assistant_plans', 0, 'suggestions', 0, 'kind'], 'email'),
            mutate(['notes'], [{'title': ''}]),
            mutate(['version'], 5),
            mutate(['list_templates', 0, 'items'], []),
            mutate(['list_templates', 0, 'name'], ''),
            mutate(['activities', party, 'checklist', 0, 'text'], ''),
            mutate(['activities', party, 'checklist', 0, 'done_dates'], ['2026-02-30']),
            mutate(['activities', party, 'checklist', 0, 'done_at'], '2026-10-17T10:00:00'),
            mutate(['activities', party, 'checklist', 0, 'secret'], 'unexpected'),
            mutate(['activities', party, 'checklist'], [{'text': 'x', 'position': i, 'done_at': None, 'done_dates': []} for i in range(51)]),
            mutate(['tasks', gift, 'checklist', 0, 'position'], True),
            mutate(['scope'], 'foundation'),
            mutate(['household', 'timezone'], 'Nowhere'),
        ]
        for change in cases:
            bad = deepcopy(good)
            change(bad)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_household(bad)
        bad = deepcopy(good)
        bad['tasks'][0]['activity'] = str(uuid.uuid4())
        before = canonical(snapshot(self.house))
        response = self.preview(bad)
        self.assertContains(response, 'refers to a family member or activity')
        self.assertFalse(PendingRestore.objects.exists())
        self.assertEqual(self.apply().status_code, 400)
        self.assertEqual(canonical(snapshot(self.house)), before)
        self.assertContains(self.preview({'format': 'home-headquarters'}), 'not supported')
        upload = SimpleUploadedFile('household.json', b'{not json', content_type='application/json')
        self.assertContains(self.client.post('/foundation/restore/', {'action': 'preview', 'backup': upload}), 'not valid JSON')

    def test_preview_belongs_to_one_parent_and_expires(self):
        exported = snapshot(self.house)
        exported['tasks'] = []
        exported['assistant_plans'][0]['suggestions'] = [s for s in exported['assistant_plans'][0]['suggestions'] if not s['task']]
        self.preview(exported)
        second = Client()
        second.force_login(self.second)
        session = second.session
        session['restore_preview'] = self.client.session['restore_preview']
        session.save()
        self.assertEqual(self.apply(second).status_code, 400)
        self.assertEqual(Task.objects.filter(household=self.house).count(), 2)
        PendingRestore.objects.update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.apply().status_code, 400)
        self.assertEqual(Task.objects.filter(household=self.house).count(), 2)
        self.assertFalse(PendingRestore.objects.exists())
        self.assertFalse(RecoveryPoint.objects.exists())

    def test_planner_edit_after_preview_rejects_stale_restore(self):
        self.preview(snapshot(self.house))
        self.client.post('/plan/task/new/', {'title': 'Edit by another parent', 'version': 0})
        self.assertEqual(self.apply().status_code, 409)
        self.assertTrue(Task.objects.filter(title='Edit by another parent').exists())
        self.assertFalse(RecoveryPoint.objects.exists())

    def test_version_one_notes_export_restores_notes_only(self):
        data = {'format': 'home-headquarters', 'version': 1, 'scope': 'foundation', 'exported_at': '2026-10-12T12:00:00+00:00',
                'household': {'name': 'Fixture', 'timezone': 'America/New_York'}, 'records': [{'title': 'Old note'}]}
        self.assertContains(self.preview(data), 'notes only')
        self.apply()
        self.assertEqual(list(SetupRecord.objects.filter(household=self.house).values_list('title', flat=True)), ['Old note'])
        self.assertEqual(Task.objects.filter(household=self.house).count(), 2)
        self.assertEqual(RecoveryPoint.objects.get().payload['version'], 4)

    def test_export_household_command(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'export.json')
            with self.assertRaises(CommandError):
                call_command('export_household', path)
            call_command('export_household', path, household=str(self.house.pk), stdout=open(os.devnull, 'w'))
            with open(path, encoding='utf-8') as handle:
                self.assertEqual(canonical(json.load(handle)), canonical(snapshot(self.house)))
            with self.assertRaises(CommandError):
                call_command('export_household', path, household=str(self.house.pk))
