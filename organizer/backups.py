"""Weekly automatic backup to Cloud Storage (FND-03).

The reminder scheduler call (every 15 minutes, 6 AM to 11 PM) also runs backup_due(): from 9 PM
on Sunday it saves the household export (the same file as Settings → Download export) to the
private bucket in BACKUP_BUCKET, and it catches up whenever the last good backup is over eight
days old. The app's account may only create files there (no reading, overwriting or deleting);
the bucket deletes backups after 12 weeks. See deploy/backup-setup.sh and docs/HOSTING.md.
"""
import json
import logging
from datetime import timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import BackupRun, Household
from .recovery import snapshot
from .views import limited, parent_only

log = logging.getLogger(__name__)
BACKUP_WEEKDAY, BACKUP_HOUR = 6, 21  # Sunday, 9 PM household time
STALE = timedelta(days=8)
RETRY_AFTER = timedelta(hours=1)

class BackupError(Exception):
    pass

def upload(name, body):
    """Create one object in the backup bucket; never overwrites an existing one."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    try:
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/devstorage.read_write'])
        response = AuthorizedSession(credentials).post(
            f'https://storage.googleapis.com/upload/storage/v1/b/{quote(settings.BACKUP_BUCKET, safe="")}/o',
            params={'uploadType': 'media', 'name': name, 'ifGenerationMatch': '0'},
            data=body, headers={'Content-Type': 'application/json'}, timeout=60)
    except Exception as error:  # noqa: BLE001 - credentials or network; reported, retried later
        raise BackupError(f'Cloud Storage could not be reached ({type(error).__name__}).') from None
    if response.status_code != 200:
        raise BackupError(f'Cloud Storage answered {response.status_code}.')

def last_good(household):
    return BackupRun.objects.filter(household=household, error='', finished_at__isnull=False).order_by('-created_at').first()

def is_due(household, now):
    if BackupRun.objects.filter(household=household, created_at__gte=now - RETRY_AFTER).exists():
        return False  # an attempt in the last hour (successful or not)
    good = last_good(household)
    if good is None or now - good.created_at >= STALE:
        return True
    zone = ZoneInfo(household.timezone)
    local = now.astimezone(zone)
    return local.weekday() == BACKUP_WEEKDAY and local.hour >= BACKUP_HOUR and good.created_at.astimezone(zone).date() != local.date()

def run(household, now=None):
    """Save one backup; returns the BackupRun with its outcome."""
    now = now or timezone.now()
    local = now.astimezone(ZoneInfo(household.timezone))
    attempt = BackupRun.objects.create(household=household, object_name=f'{household.pk}/home-headquarters-{local:%Y-%m-%d-%H%M}.json')
    try:
        with transaction.atomic():
            locked = Household.objects.select_for_update().get(pk=household.pk)
            body = json.dumps(snapshot(locked), separators=(',', ':')).encode()
        upload(attempt.object_name, body)
    except BackupError as error:
        attempt.error = str(error)[:255]
        attempt.save(update_fields=['error'])
        log.warning('Backup failed for a household: %s', attempt.error)
        return attempt
    attempt.size, attempt.finished_at = len(body), timezone.now()
    attempt.save(update_fields=['size', 'finished_at'])
    BackupRun.objects.filter(household=household, created_at__lt=now - timedelta(days=120)).delete()
    return attempt

def backup_due(now=None):
    """Called from the scheduler run. Does nothing until BACKUP_BUCKET is set."""
    if not settings.BACKUP_BUCKET:
        return {'saved': 0, 'failed': 0}
    now = now or timezone.now()
    saved = failed = 0
    for household in Household.objects.all():
        if is_due(household, now):
            if run(household, now).error:
                failed += 1
            else:
                saved += 1
    return {'saved': saved, 'failed': failed}

@parent_only
@require_POST
def backup_now(request):
    if not settings.BACKUP_BUCKET:
        messages.error(request, 'Automatic backup is not set up on the server yet.')
    elif limited('backup-now:' + str(request.household.pk), 3):
        messages.error(request, 'A few backups were just made. Please wait a while before trying again.')
    else:
        attempt = run(request.household)
        if attempt.error:
            messages.error(request, f'The backup could not be saved: {attempt.error}')
        else:
            messages.success(request, f'Backup saved ({max(1, attempt.size // 1024)} KB).')
    return redirect('foundation')
