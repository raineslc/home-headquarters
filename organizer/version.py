"""Which code is running, so a missed or failed deploy is visible in Settings."""
import os
from django.utils import timezone

REPOSITORY = 'https://github.com/raineslc/home-headquarters'
# Recorded when the app process loads; on Render this is the latest deploy or wake-up.
STARTED = timezone.now()

def info():
    commit = os.getenv('RENDER_GIT_COMMIT', '')
    return {'commit': commit[:7], 'commit_url': f'{REPOSITORY}/commit/{commit}' if commit else '',
            'branch': os.getenv('RENDER_GIT_BRANCH', ''), 'started': STARTED}
