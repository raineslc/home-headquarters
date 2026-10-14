from django.apps import AppConfig

class OrganizerConfig(AppConfig):
    name = 'organizer'

    def ready(self):
        from . import google_writes  # noqa: F401  registers the Google write hooks
