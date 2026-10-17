import json
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from .models import Activity, ChecklistItem, FamilyMember, Household, ListTemplate, LunchPlan, Membership, Task
from .recovery import snapshot

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ChecklistTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Fixture family')
        self.other = Household.objects.create(name='Other fixture family')
        users = get_user_model().objects
        self.parent = users.create_user('fixture@example.test')
        self.outsider = users.create_user('outsider@example.test')
        Membership.objects.create(user=self.parent, household=self.house)
        Membership.objects.create(user=self.outsider, household=self.other)
        self.client.force_login(self.parent)
        self.child = FamilyMember.objects.create(household=self.house, name='Fixture child', role='child')
        self.swim = Activity.objects.create(household=self.house, title='Swim', start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
                                            start_time='17:00', end_time='18:00', recurrence='FREQ=WEEKLY;BYDAY=MO')
        self.party = Activity.objects.create(household=self.house, title='Party', start_date=date(2026, 10, 17), end_date=date(2026, 10, 17))
        self.template = ListTemplate.objects.create(household=self.house, name='Swim bag', items=['Towel', 'Goggles', 'Snack'])

    def act(self, kind, owner, **data):
        return self.client.post(f'/checklist/{kind}/{owner.pk}/', data)

    def test_saved_lists_can_be_created_edited_and_deleted(self):
        response = self.client.post('/lists/', {'name': 'Field trip', 'items': 'Lunch\n\n  Water   bottle \nHat'})
        self.assertEqual(response.status_code, 302)
        saved = ListTemplate.objects.get(name='Field trip')
        self.assertEqual(saved.items, ['Lunch', 'Water bottle', 'Hat'])
        self.assertContains(self.client.get('/lists/'), 'Field trip')
        self.assertContains(self.client.post('/lists/', {'name': 'Too long', 'items': '\n'.join(f'Item {i}' for i in range(51))}), 'up to 50 items')
        self.client.post(f'/lists/{saved.pk}/', {'name': 'Field trip', 'items': 'Lunch'})
        saved.refresh_from_db()
        self.assertEqual(saved.items, ['Lunch'])
        self.client.post(f'/lists/{saved.pk}/', {'action': 'delete'})
        self.assertFalse(ListTemplate.objects.filter(pk=saved.pk).exists())

    def test_add_template_tick_and_remove_on_a_one_off_activity(self):
        self.act('activity', self.party, action='add', text='  Birthday   card ')
        self.act('activity', self.party, action='template', template=str(self.template.pk))
        self.act('activity', self.party, action='template', template=str(self.template.pk))  # duplicates are skipped
        self.assertEqual(list(self.party.checklist_items.values_list('text', flat=True)), ['Birthday card', 'Towel', 'Goggles', 'Snack'])
        towel = self.party.checklist_items.get(text='Towel')
        response = self.act('activity', self.party, action='done', item=str(towel.pk), next=f'/activity/{self.party.pk}/#checklist')
        self.assertRedirects(response, f'/activity/{self.party.pk}/#checklist', fetch_redirect_response=False)
        towel.refresh_from_db()
        self.assertIsNotNone(towel.done_at)
        page = self.client.get(f'/activity/{self.party.pk}/')
        self.assertContains(page, '1/4 done')
        self.act('activity', self.party, action='undone', item=str(towel.pk))
        towel.refresh_from_db()
        self.assertIsNone(towel.done_at)
        self.act('activity', self.party, action='remove', item=str(towel.pk))
        self.assertFalse(ChecklistItem.objects.filter(pk=towel.pk).exists())
        self.assertEqual(self.act('activity', self.party, action='done', item=str(towel.pk)).status_code, 409)
        # Unsafe redirect targets fall back to the plan's own page.
        response = self.act('activity', self.party, action='add', text='Gift', next='https://example.com/')
        self.assertRedirects(response, f'/activity/{self.party.pk}/', fetch_redirect_response=False)

    def test_repeating_activity_keeps_ticks_per_occurrence(self):
        self.act('activity', self.swim, action='template', template=str(self.template.pk))
        towel = self.swim.checklist_items.get(text='Towel')
        self.act('activity', self.swim, action='done', item=str(towel.pk), occurrence='2026-10-19')
        towel.refresh_from_db()
        self.assertEqual((towel.done_dates, towel.done_at), (['2026-10-19'], None))
        self.assertContains(self.client.get(f'/activity/{self.swim.pk}/?occurrence=2026-10-19'), '1/3 done for Oct 19')
        self.assertContains(self.client.get(f'/activity/{self.swim.pk}/?occurrence=2026-10-26'), '0/3 done for Oct 26')
        self.assertEqual(self.act('activity', self.swim, action='done', item=str(towel.pk), occurrence='soon').status_code, 400)

    def test_other_households_cannot_see_or_change_checklists(self):
        item = ChecklistItem.objects.create(household=self.house, activity=self.party, text='Private item')
        self.client.force_login(self.outsider)
        self.assertEqual(self.act('activity', self.party, action='add', text='Intruder').status_code, 404)
        self.assertEqual(self.client.get(f'/lists/{self.template.pk}/').status_code, 404)
        foreign = Activity.objects.create(household=self.other, title='Theirs', start_date=date(2026, 10, 17), end_date=date(2026, 10, 17))
        self.act('activity', foreign, action='template', template=str(self.template.pk))
        self.assertFalse(foreign.checklist_items.exists())
        self.act('activity', foreign, action='remove', item=str(item.pk))
        self.assertTrue(ChecklistItem.objects.filter(pk=item.pk).exists())
        self.assertEqual(self.act('member', self.party, action='add', text='x').status_code, 404)

    def test_task_checklist_progress_and_fresh_copy_for_next_repeat(self):
        task = Task.objects.create(household=self.house, title='Pack for swim', due_date=date(2026, 10, 19), recurrence='FREQ=WEEKLY;BYDAY=MO',
                                   recurrence_start=date(2026, 10, 19), series_key='0b5c6e2a-1c2d-4e5f-8a9b-0c1d2e3f4a5b')
        self.act('task', task, action='template', template=str(self.template.pk))
        towel = task.checklist_items.get(text='Towel')
        self.act('task', task, action='done', item=str(towel.pk))
        self.assertContains(self.client.get('/tasks/'), '☑ 1/3')
        self.assertContains(self.client.get(f'/plan/task/{task.pk}/edit/'), 'Goggles')
        self.client.post(f'/tasks/{task.pk}/complete/', {'version': task.version})
        following = Task.objects.get(series_key=task.series_key, due_date=date(2026, 10, 26))
        self.assertEqual([(i.text, i.done_at) for i in following.checklist_items.all()], [('Towel', None), ('Goggles', None), ('Snack', None)])
        # Reopening and completing again does not add a second copy.
        task.refresh_from_db()
        self.client.post(f'/tasks/{task.pk}/complete/', {'version': task.version})
        task.refresh_from_db()
        self.client.post(f'/tasks/{task.pk}/complete/', {'version': task.version})
        self.assertEqual(following.checklist_items.count(), 3)

    def test_tonights_prep_appears_after_five_pm(self):
        ChecklistItem.objects.create(household=self.house, activity=self.swim, text='Goggles', position=0)
        ChecklistItem.objects.create(household=self.house, activity=self.swim, text='Towel', position=1, done_dates=['2026-10-19'])
        Task.objects.create(household=self.house, title='Sign permission slip', due_date=date(2026, 10, 19))
        LunchPlan.objects.create(household=self.house, child=self.child, date=date(2026, 10, 19), choice='pack')
        zone = ZoneInfo(self.house.timezone)
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 18, 16, 59, tzinfo=zone)):
            self.assertNotContains(self.client.get('/'), 'Tonight’s prep')
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 18, 17, 30, tzinfo=zone)):
            page = self.client.get('/')
        self.assertContains(page, 'Tonight’s prep')
        self.assertContains(page, 'Tomorrow · Mon, Oct 19')
        self.assertContains(page, 'Swim')
        self.assertContains(page, '<strong>Bring:</strong> Goggles', html=False)
        self.assertNotContains(page, 'Bring:</strong> Goggles, Towel')
        self.assertContains(page, 'Sign permission slip')
        self.assertContains(page, 'Pack lunch for Fixture child')

    def test_version_three_exports_restore_without_lists(self):
        ChecklistItem.objects.create(household=self.house, activity=self.party, text='Card')
        exported = snapshot(self.house)
        self.assertEqual(exported['version'], 5)
        self.assertEqual(exported['list_templates'], [{'name': 'Swim bag', 'items': ['Towel', 'Goggles', 'Snack']}])
        old = dict(exported, version=3)
        del old['list_templates']
        old['activities'] = [{k: v for k, v in row.items() if k != 'checklist'} for row in exported['activities']]
        old['tasks'] = [{k: v for k, v in row.items() if k not in ('checklist', 'repeat_after_done')} for row in exported['tasks']]
        self.client.force_login(self.outsider)
        upload = SimpleUploadedFile('household.json', json.dumps(old).encode(), content_type='application/json')
        self.assertContains(self.client.post('/foundation/restore/', {'action': 'preview', 'backup': upload}), '0 saved lists')
        self.assertEqual(self.client.post('/foundation/restore/', {'action': 'apply'}).status_code, 302)
        self.assertEqual(Activity.objects.filter(household=self.other).count(), 2)
        self.assertFalse(ListTemplate.objects.filter(household=self.other).exists())
        self.assertFalse(ChecklistItem.objects.filter(household=self.other).exists())
