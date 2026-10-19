"""Phone reminders by Web Push (REM-01 to REM-03, AI-05).

Cloud Scheduler calls /jobs/reminders/ every 15 minutes (6 AM to 11 PM Eastern) with a Google-signed
identity token. Each run works out, from the current plans, which reminders are due and sends
each one once to every phone that turned reminders on. Because reminders are computed from the
plans on every run, moving, deleting or completing a plan changes or cancels its reminder; a moved
plan has a new reminder key, so it is reminded again for the new time.
"""
import json
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.contrib import messages
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from . import webpush
from .models import Activity, PushSubscription, ReminderDelivery, Task
from .recurrence import expand
from .views import parent_only

log = logging.getLogger(__name__)
# Untimed plans (all-day activities, tasks without a time) are treated as starting at 8 AM.
DEFAULT_TIME = time(8, 0)
# A run sends reminders due up to half an interval ahead, so each is at most ~8 minutes early or late.
AHEAD = timedelta(minutes=8)
# Reminders missed overnight (the scheduler pauses 11 PM to 6 AM) still go out if the plan hasn't started.
LOOKBACK = timedelta(hours=12)
MAX_ATTEMPTS = 3
LOCK = 47290004

def at(day, clock, zone):
    return datetime.combine(day, clock or DEFAULT_TIME).replace(tzinfo=ZoneInfo(zone))

def when_text(start, now, zone, untimed):
    local, today = start.astimezone(ZoneInfo(zone)), now.astimezone(ZoneInfo(zone)).date()
    day = 'today' if local.date() == today else 'tomorrow' if local.date() == today + timedelta(days=1) else local.strftime('%A, %b ') + str(local.day)
    return day if untimed else f'{day} at {local.strftime("%I:%M %p").lstrip("0")}'

def due_reminders(household, now):
    """Reminders whose time has come (within AHEAD) for plans that haven't started or been due yet."""
    zone = household.timezone
    today = now.astimezone(ZoneInfo(zone)).date()
    start, end = today - timedelta(days=1), today + timedelta(days=3)
    found = []
    activities = Activity.objects.filter(household=household, reminder_minutes__isnull=False).prefetch_related('participants')
    for event in expand(activities.filter(recurrence='', start_date__lte=end, end_date__gte=start) |
                        activities.exclude(recurrence='').filter(start_date__lte=end), start, end):
        untimed = event.all_day or event.start_time is None
        begins = at(event.start_date, None if event.all_day else event.start_time, zone if untimed else event.timezone)
        remind = begins - timedelta(minutes=event.reminder_minutes)
        if now - LOOKBACK <= remind <= now + AHEAD and begins > now:
            pk = event.activity.pk if hasattr(event, 'instance_date') else event.pk
            query = event.detail_query if hasattr(event, 'instance_date') else ''
            people = ', '.join(person.name for person in event.participants.all())
            body = 'Starts ' + when_text(begins, now, zone, untimed) + (f' · {event.location}' if event.location else '') + (f' · {people}' if people else '')
            found.append({'key': f'a:{pk}:{begins.isoformat()}:{event.reminder_minutes}', 'title': event.title, 'body': body,
                          'url': f'/activity/{pk}/{query}'})
    tasks = Task.objects.filter(household=household, completed_at__isnull=True, reminder_minutes__isnull=False,
                                due_date__range=(start, end)).select_related('assignee')
    for task in tasks:
        due = at(task.due_date, task.due_time, zone)
        remind = due - timedelta(minutes=task.reminder_minutes)
        if now - LOOKBACK <= remind <= now + AHEAD and due > now:
            body = 'Due ' + when_text(due, now, zone, task.due_time is None) + (f' · {task.assignee.name}' if task.assignee else '')
            found.append({'key': f't:{task.pk}:{due.isoformat()}:{task.reminder_minutes}', 'title': task.title, 'body': body,
                          'url': f'/plan/task/{task.pk}/edit/'})
    return found

def deliver(delivery, message):
    """Send one claimed delivery. Returns True when sent; removes devices that turned reminders off."""
    try:
        webpush.send(delivery.subscription, message)
    except Exception as error:  # noqa: BLE001 - one bad device must not stop the others
        if isinstance(error, webpush.PushError) and error.gone:
            delivery.subscription.delete()
            return False
        delivery.attempts += 1
        delivery.last_error = (str(error) if isinstance(error, webpush.PushError) else type(error).__name__)[:200]
        delivery.save(update_fields=['attempts', 'last_error'])
        return False
    delivery.attempts += 1
    delivery.sent_at = timezone.now()
    delivery.save(update_fields=['attempts', 'sent_at'])
    PushSubscription.objects.filter(pk=delivery.subscription_id).update(last_sent_at=delivery.sent_at)
    return True

def send_due(now=None):
    """Send every due reminder once per device. Safe to run concurrently or repeatedly.

    Each delivery is committed as soon as it is sent, so a run that stops halfway never sends
    the same reminder twice."""
    now = now or timezone.now()
    sent = failed = 0
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [LOCK])
        if not cursor.fetchone()[0]:
            return {'sent': 0, 'failed': 0, 'busy': True}
    try:
        devices = {}
        for subscription in PushSubscription.objects.select_related('household'):
            devices.setdefault(subscription.household, []).append(subscription)
        for household, subscriptions in devices.items():
            for reminder in due_reminders(household, now):
                message = {'title': reminder['title'], 'body': reminder['body'], 'url': reminder['url'], 'tag': reminder['key'][:60]}
                for subscription in subscriptions:
                    delivery, _ = ReminderDelivery.objects.get_or_create(subscription=subscription, key=reminder['key'], defaults={'household': household})
                    if delivery.sent_at or delivery.attempts >= MAX_ATTEMPTS:
                        continue
                    if deliver(delivery, message):
                        sent += 1
                    else:
                        failed += 1
        ReminderDelivery.objects.filter(created_at__lt=now - timedelta(days=14)).delete()
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [LOCK])
    return {'sent': sent, 'failed': failed, 'busy': False}

def scheduler_identity(request):
    """The verified email of a Google-signed identity token for this endpoint, or None."""
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer ') or not settings.JOB_INVOKER_EMAIL or not settings.APP_HOSTNAME:
        return None
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    try:
        claims = id_token.verify_oauth2_token(header[7:], Request(), audience=f'https://{settings.APP_HOSTNAME}/jobs/reminders/')
    except ValueError:
        return None
    email = (claims.get('email') or '').lower()
    return email if claims.get('email_verified') and email == settings.JOB_INVOKER_EMAIL else None

def google_due():
    """Scheduled Google Calendar sync and write retries (GGL-04). Never stops the reminder run."""
    from . import google_service, google_writes
    if not google_service.configured():
        return {'synced': 0, 'failed': 0, 'retried': 0}
    try:
        result = google_service.sync_due()
        result['retried'] = google_writes.retry_failed()
    except Exception:  # noqa: BLE001 - reminders already went out; report and carry on
        log.exception('Scheduled Google sync failed')
        return {'synced': 0, 'failed': 1, 'retried': 0}
    return result

@csrf_exempt
@require_POST
def reminders_job(request):
    """Cloud Scheduler's call: send due reminders first, then refresh Google calendars."""
    if scheduler_identity(request) is None:
        return HttpResponse('Not allowed.', status=403)
    result = send_due()
    log.warning('Reminder run: %(sent)s sent, %(failed)s failed', result)
    result['google'] = google_due()
    log.warning('Google sync run: %(synced)s synced, %(failed)s failed, %(retried)s retried', result['google'])
    result['backup'] = backup_due()
    return JsonResponse(result)

def backup_due():
    """Weekly backup (FND-03). Never fails the scheduler run."""
    from . import backups
    try:
        return backups.backup_due()
    except Exception:  # noqa: BLE001
        log.exception('Scheduled backup failed')
        return {'saved': 0, 'failed': 1}

def device_label(request):
    agent = request.headers.get('User-Agent', '')
    kind = 'Android phone' if 'Android' in agent else 'iPhone' if 'iPhone' in agent else 'Computer'
    browser = 'Edge' if 'Edg/' in agent else 'Chrome' if 'Chrome/' in agent else 'Firefox' if 'Firefox/' in agent else 'Safari' if 'Safari/' in agent else 'browser'
    return f'{kind} · {browser}'

def read_json(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return None
    return data if isinstance(data, dict) else None

@parent_only
@require_POST
def subscribe(request):
    data = read_json(request)
    keys = data.get('keys') if data else None
    endpoint = data.get('endpoint') if data else None
    if not webpush.public_key():
        return JsonResponse({'error': 'Phone reminders are not set up on the server yet.'}, status=503)
    if not webpush.allowed_endpoint(endpoint) or not isinstance(keys, dict) or \
            not all(isinstance(keys.get(name), str) and 0 < len(keys[name]) <= limit for name, limit in (('p256dh', 200), ('auth', 100))):
        return JsonResponse({'error': 'This browser sent an unsupported subscription.'}, status=400)
    try:
        if len(webpush.unb64(keys['p256dh'])) != 65 or len(webpush.unb64(keys['auth'])) != 16:
            raise ValueError
    except ValueError:
        return JsonResponse({'error': 'This browser sent an unsupported subscription.'}, status=400)
    PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={
        'household': request.household, 'user': request.user, 'p256dh': keys['p256dh'], 'auth': keys['auth'], 'label': device_label(request)})
    return JsonResponse({'ok': True, 'devices': PushSubscription.objects.filter(household=request.household).count()})

@parent_only
@require_POST
def unsubscribe(request):
    data = read_json(request) or {}
    PushSubscription.objects.filter(household=request.household, endpoint=data.get('endpoint') or '').delete()
    return JsonResponse({'ok': True})

@parent_only
@require_POST
def test_push(request):
    data = read_json(request) or {}
    subscription = PushSubscription.objects.filter(household=request.household, endpoint=data.get('endpoint') or '').first()
    if subscription is None:
        return JsonResponse({'error': 'Turn on reminders on this device first.'}, status=404)
    try:
        webpush.send(subscription, {'title': 'Home Headquarters', 'body': 'Reminders are on for this device.', 'url': '/settings/', 'tag': 'test'})
    except webpush.PushError as error:
        if error.gone:
            subscription.delete()
        return JsonResponse({'error': f'The test could not be sent: {error}'}, status=502)
    return JsonResponse({'ok': True})

@parent_only
@require_POST
def remove_device(request, pk):
    PushSubscription.objects.filter(household=request.household, pk=pk).delete()
    messages.success(request, 'That device will no longer receive reminders.')
    return redirect('/settings/#reminders')
