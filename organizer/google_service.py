"""Read-only Google access. Provider payloads and credentials must never be logged."""
from datetime import date, datetime, timedelta, time
from functools import partial
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import GoogleAuthError
from google_auth_oauthlib.flow import Flow
import requests
from .models import GoogleCalendar, GoogleConnection, GoogleEvent

SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email',
          'https://www.googleapis.com/auth/calendar.calendarlist.readonly',
          'https://www.googleapis.com/auth/calendar.events.readonly']
COLORS = ['blue', 'purple', 'orange', 'green']

class GoogleUnavailable(Exception):
    pass

class ReconnectRequired(GoogleUnavailable):
    pass

def configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_TOKEN_KEY)

def cipher():
    return Fernet(settings.GOOGLE_TOKEN_KEY.encode())

def flow(**kwargs):
    return Flow.from_client_config({'web': {
        'client_id': settings.GOOGLE_CLIENT_ID, 'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }}, scopes=SCOPES, redirect_uri=settings.GOOGLE_REDIRECT_URI, **kwargs)

def access_token(connection):
    try:
        refresh = cipher().decrypt(connection.encrypted_refresh_token.encode()).decode()
        credentials = Credentials(None, refresh_token=refresh,
            token_uri='https://oauth2.googleapis.com/token', client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET, scopes=SCOPES)
        credentials.refresh(partial(Request(session=requests.Session()), timeout=20))
        return credentials.token
    except GoogleAuthError as error:
        # Only a rejected grant requires reconnect; temporary outages remain retryable.
        if 'invalid_grant' in str(error):
            GoogleConnection.objects.filter(pk=connection.pk).update(needs_reconnect=True)
            raise ReconnectRequired('Google access expired. Connect this account again.') from None
        raise GoogleUnavailable('Google is temporarily unavailable. Try syncing again shortly.') from None
    except (InvalidToken, ValueError, requests.RequestException):
        raise GoogleUnavailable('The connection could not be opened. Please try again or reconnect.') from None

def get_json(url, token, params=None):
    try:
        response = requests.get(url, headers={'Authorization': 'Bearer ' + token},
                                params=params, timeout=(5, 20), allow_redirects=False)
        if response.status_code == 401:
            raise ReconnectRequired('Google access expired. Connect this account again.')
        if response.status_code in (403, 404):
            raise GoogleUnavailable('Google no longer allows access to this calendar. Refresh the calendar list or reconnect.')
        if response.status_code != 200:
            raise GoogleUnavailable('Google could not sync right now. Your last saved events are still shown. Try again shortly.')
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (requests.RequestException, ValueError):
        raise GoogleUnavailable('Google could not be reached. Try again shortly.') from None

def paginated(url, token, params=None):
    items, params = [], dict(params or {})
    for _ in range(100):
        page = get_json(url, token, params)
        items.extend(page.get('items', []))
        if not page.get('nextPageToken'):
            return items
        params['pageToken'] = page['nextPageToken']
    raise GoogleUnavailable('This calendar is too large for preview sync. No partial changes were saved.')

def refresh_calendars(connection, token=None):
    token = token or access_token(connection)
    entries = paginated('https://www.googleapis.com/calendar/v3/users/me/calendarList', token, {'maxResults': 250})
    with transaction.atomic():
        locked = GoogleConnection.objects.select_for_update().get(pk=connection.pk)
        seen = []
        for index, entry in enumerate(entries):
            if entry.get('deleted') or entry.get('accessRole') not in ('reader', 'writer', 'owner'):
                continue
            external_id = entry['id']
            calendar, created = GoogleCalendar.objects.get_or_create(connection=locked, external_id=external_id,
                defaults={'name': entry.get('summary', 'Google calendar')[:255], 'access_role': entry['accessRole'], 'color': COLORS[index % len(COLORS)]})
            calendar.name = entry.get('summary', 'Google calendar')[:255]
            calendar.access_role = entry['accessRole']
            calendar.save(update_fields=['name', 'access_role'])
            seen.append(calendar.pk)
        # Lost permission must immediately remove previously cached personal details.
        locked.calendars.exclude(pk__in=seen).delete()
        locked.needs_reconnect = False
        locked.version += 1
        locked.save(update_fields=['needs_reconnect', 'version'])

def normalize_event(raw, calendar, household_timezone):
    if raw.get('status') == 'cancelled':
        return None
    zone = ZoneInfo(household_timezone)
    start, end = raw['start'], raw['end']
    all_day = 'date' in start
    if all_day:
        start_date, end_date = date.fromisoformat(start['date']), date.fromisoformat(end['date']) - timedelta(days=1)
        start_time = end_time = None
    else:
        first, last = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00')), datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
        if first.tzinfo is None or last.tzinfo is None or last <= first:
            raise ValueError('Invalid event interval')
        first, last = first.astimezone(zone), last.astimezone(zone)
        start_date, end_date = first.date(), (last - timedelta(microseconds=1)).date()
        start_time, end_time = first.time().replace(tzinfo=None), last.time().replace(tzinfo=None)
    if end_date < start_date:
        raise ValueError('Invalid all-day interval')
    busy = calendar.visibility == 'busy' or raw.get('visibility') == 'private'
    link = raw.get('htmlLink', '')
    if urlparse(link).scheme != 'https' or urlparse(link).hostname not in ('calendar.google.com', 'www.google.com'):
        link = ''
    return GoogleEvent(calendar=calendar, external_id=raw['id'], title='Busy' if busy else raw.get('summary', '(Untitled event)')[:500],
        start_date=start_date, end_date=end_date, start_time=start_time, end_time=end_time, all_day=all_day,
        location='' if busy else raw.get('location', '')[:1000], html_link='' if busy else link[:2048])

def sync_calendar(calendar, token=None):
    """Atomic bounded snapshots include recurrence exceptions and remove deleted instances.

    Re-fetching a complete window is intentionally used instead of mixing incompatible
    syncToken/timeMin/singleEvents parameters. Failed pages never replace the old snapshot.
    """
    connection = calendar.connection
    version = connection.version
    token = token or access_token(connection)
    today = timezone.localdate(timezone=ZoneInfo(connection.household.timezone))
    lower, upper = today - timedelta(days=90), today + timedelta(days=366)
    zone = ZoneInfo(connection.household.timezone)
    try:
        rows = paginated('https://www.googleapis.com/calendar/v3/calendars/' + quote(calendar.external_id, safe='') + '/events', token,
            {'singleEvents': 'true', 'showDeleted': 'false', 'maxResults': 2500,
             'timeMin': datetime.combine(lower, time.min, zone).isoformat(),
             'timeMax': datetime.combine(upper, time.min, zone).isoformat()})
        events = [normalize_event(row, calendar, connection.household.timezone) for row in rows]
    except (KeyError, TypeError, ValueError):
        raise GoogleUnavailable('An event from Google could not be read. No partial changes were saved.') from None
    with transaction.atomic():
        locked = GoogleConnection.objects.select_for_update().filter(pk=connection.pk).first()
        if not locked or locked.version != version:
            raise GoogleUnavailable('Calendar choices changed during sync. Sync again to use the latest choices.')
        current = GoogleCalendar.objects.filter(pk=calendar.pk).first()
        if not current or current.visibility == 'off':
            return
        current.events.all().delete()
        # A page retry or repeated provider ID cannot create duplicate events.
        unique = {event.external_id: event for event in events if event is not None}
        GoogleEvent.objects.bulk_create(unique.values())
        current.last_synced = timezone.now()
        current.window_start, current.window_end, current.sync_error = lower, upper - timedelta(days=1), ''
        current.save(update_fields=['last_synced', 'window_start', 'window_end', 'sync_error'])

def sync_connection(connection):
    with transaction.atomic():
        connection = GoogleConnection.objects.select_for_update().select_related('household').get(pk=connection.pk)
        connection.version += 1
        connection.save(update_fields=['version'])
    token = access_token(connection)
    for calendar in connection.calendars.exclude(visibility='off'):
        try:
            sync_calendar(calendar, token)
        except GoogleUnavailable as error:
            GoogleCalendar.objects.filter(pk=calendar.pk).update(sync_error=str(error))
            raise

def shared_events(household, start, end):
    rows = GoogleEvent.objects.filter(calendar__connection__household=household,
        calendar__connection__owner__membership__active=True,
        calendar__connection__owner__membership__household=household,
        calendar__visibility__in=['busy', 'details'], start_date__lte=end, end_date__gte=start).select_related('calendar__connection__owner')
    unique = {}
    for event in rows:
        key = (event.calendar.external_id, event.external_id)
        # The more private choice wins if both accounts select the same shared calendar.
        if key not in unique or event.title == 'Busy':
            unique[key] = event
    return list(unique.values())
