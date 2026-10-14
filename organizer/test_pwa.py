import json
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import Client, TestCase, override_settings
from .models import Household, Membership

@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PhoneAppTests(TestCase):
    def setUp(self):
        self.house = Household.objects.create(name='Private household name')
        self.parent = get_user_model().objects.create_user('parent@example.test', first_name='Private Parent')
        Membership.objects.create(user=self.parent, household=self.house)

    def test_manifest_is_installable_and_public(self):
        response = Client().get('/manifest.webmanifest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        data = json.loads(response.content)
        self.assertEqual((data['display'], data['start_url'], data['scope'], data['short_name']), ('standalone', '/?source=app', '/', 'Home HQ'))
        sizes = {(icon['sizes'], icon.get('purpose', 'any')) for icon in data['icons']}
        self.assertTrue({('192x192', 'any'), ('512x512', 'any'), ('512x512', 'maskable')} <= sizes)
        for icon in data['icons']:
            self.assertTrue(finders.find(icon['src'].removeprefix('/static/')), icon['src'])
        self.assertEqual([s['name'] for s in data['shortcuts']], ['Add activity', 'Tasks', 'Lunches'])

    def test_service_worker_caches_only_app_files(self):
        response = Client().get('/sw.js')
        self.assertEqual(response['Content-Type'], 'application/javascript')
        body = response.content.decode()
        self.assertIn('/static/app.css', body)
        self.assertIn("'/offline/'", body.replace('"', "'"))
        self.assertIn("request.mode === 'navigate'", body)
        self.assertNotIn('/tasks/', body)
        self.assertEqual(body, Client().get('/sw.js').content.decode())  # stable between requests

    def test_offline_page_never_contains_household_data(self):
        client = Client()
        client.force_login(self.parent)
        response = client.get('/offline/')
        self.assertContains(response, 'You’re offline')
        for private in ('Private Parent', 'Private household name', 'csrfmiddlewaretoken', 'Sign out'):
            self.assertNotContains(response, private)

    def test_pages_link_the_manifest_and_offer_install(self):
        self.client.force_login(self.parent)
        page = self.client.get('/')
        self.assertContains(page, '<link rel="manifest" href="/manifest.webmanifest">', html=False)
        self.assertContains(page, 'name="theme-color"')
        self.assertContains(page, 'data-install-banner hidden')
        self.assertContains(self.client.get('/settings/'), 'Install app')
        self.assertNotContains(Client().get('/sign-in/'), 'data-install-banner')
