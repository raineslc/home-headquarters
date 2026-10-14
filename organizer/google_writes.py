"""Copies chosen activities to the household's app-created family Google calendar (GGL-02).

Home Headquarters is the source of truth. Writes run after the local change commits, so a
Google outage never blocks or rolls back a plan. Each outcome is recorded on the activity
(google_state) for retry or conflict resolution in the activity page.

- Idempotent creates: the Google event ID is derived from the activity, so a retried insert
  that already succeeded becomes an update instead of a duplicate.
- Concurrent edits: updates send the stored ETag; a change made in Google is never silently
  overwritten (state "conflict" until a parent chooses).
- Deletions: deleting an activity queues its Google copy for removal; failures stay queued.
- Repeating series send their RRULE and skipped dates; a changed occurrence is its own event.

Provider payloads and credentials must never be logged.
"""
import contextvars
import secrets
from datetime import datetime, time, timedelta, timezone as utc_timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo
import requests
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from . import google_service as google
from .models import Activity, FamilyCalendar, GoogleCalendar, GoogleConnection, GooglePendingDeletion
from .recurrence import parse_parts

API = 'https://www.googleapis.com/calendar/v3'
# Restoring a backup replaces activities wholesale; it must not rewrite or delete Google events.
paused = contextvars.ContextVar('google_writes_paused', default=False)

class Conflict(google.GoogleUnavailable):
    pass

class Missing(google.GoogleUnavailable):
    pass

def family_calendar(household):
    return FamilyCalendar.objects.filter(household=household).select_related('calendar__connection').first()

def call(method, url, token, body=None, etag=None):
    headers = {'Authorization': 'Bearer ' + token}
    if etag:
        headers['If-Match'] = etag
    try:
        response = requests.request(method, url, headers=headers, json=body, timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise google.GoogleUnavailable('Google could not be reached. The change is saved here; retry the Google update shortly.') from None
    if response.status_code == 401:
        raise google.ReconnectRequired('Google access expired. Reconnect the account that owns the family calendar.')
    if response.status_code == 403:
        raise google.GoogleUnavailable('Google refused the update. The family calendar may have been removed or its permission withdrawn.')
    if response.status_code in (404, 410):
        raise Missing('This event was deleted in Google.')
    if response.status_code == 412:
        raise Conflict('This event was changed in Google since the last update.')
    if response.status_code == 409:
        raise Conflict('duplicate')
    if response.status_code not in (200, 201, 204):
        raise google.GoogleUnavailable('Google could not save the change right now. Retry shortly.')
    if response.status_code == 204 or not response.content:
        return {}
    try:
        result = response.json()
    except ValueError:
        raise google.GoogleUnavailable('Google returned an unreadable reply. Retry shortly.') from None
    if not isinstance(result, dict):
        raise google.GoogleUnavailable('Google returned an unreadable reply. Retry shortly.')
    return result

def create_family_calendar(connection, token):
    """Create the household's Home Headquarters calendar in this parent's Google account."""
    household = connection.household
    created = call('POST', API + '/calendars', token, {'summary': 'Home Headquarters', 'timeZone': household.timezone,
                                                      'description': 'Family activities added from Home Headquarters.'})
    if not created.get('id'):
        raise google.GoogleUnavailable('Google did not create the calendar. Please try again.')
    with transaction.atomic():
        calendar, _ = GoogleCalendar.objects.get_or_create(connection=connection, external_id=created['id'],
            defaults={'name': created.get('summary', 'Home Headquarters')[:255], 'access_role': 'owner', 'color': 'green'})
        FamilyCalendar.objects.filter(household=household).delete()
        return FamilyCalendar.objects.create(household=household, calendar=calendar)

def event_id(activity, fresh=False):
    # Google event IDs use base32hex (0-9, a-v); UUID hex digits are a valid subset.
    suffix = secrets.token_hex(3) if fresh else ''
    return 'hhq' + activity.pk.hex + suffix

def google_until(rule, activity):
    """Express a date-only UNTIL in the form Google expects for timed or all-day events."""
    parts = parse_parts(rule)
    if 'UNTIL' not in parts or activity.all_day:
        return rule
    until = datetime.strptime(parts['UNTIL'], '%Y%m%d').date()
    last = datetime.combine(until, time(23, 59, 59), ZoneInfo(activity.timezone)).astimezone(utc_timezone.utc)
    return rule.replace('UNTIL=' + parts['UNTIL'], 'UNTIL=' + last.strftime('%Y%m%dT%H%M%SZ'))

def event_body(activity):
    people = ', '.join(person.name for person in activity.participants.all())
    notes = '\n\n'.join(part for part in [f'Who: {people}' if people else '', activity.notes,
                                         'Added from Home Headquarters. Edit it there so both copies stay in step.'] if part)
    body = {'summary': activity.title, 'location': activity.location, 'description': notes,
            'extendedProperties': {'private': {'homeHeadquarters': str(activity.pk)}}}
    if activity.all_day:
        body['start'] = {'date': activity.start_date.isoformat()}
        body['end'] = {'date': (activity.end_date + timedelta(days=1)).isoformat()}
    else:
        body['start'] = {'dateTime': datetime.combine(activity.start_date, activity.start_time).isoformat(), 'timeZone': activity.timezone}
        body['end'] = {'dateTime': datetime.combine(activity.end_date, activity.end_time).isoformat(), 'timeZone': activity.timezone}
    if activity.recurrence:
        lines = ['RRULE:' + google_until(activity.recurrence, activity)]
        for value in sorted(activity.recurrence_exdates):
            day = datetime.strptime(value, '%Y-%m-%d')
            if activity.all_day:
                lines.append('EXDATE;VALUE=DATE:' + day.strftime('%Y%m%d'))
            else:
                lines.append(f'EXDATE;TZID={activity.timezone}:' + datetime.combine(day.date(), activity.start_time).strftime('%Y%m%dT%H%M%S'))
        body['recurrence'] = lines
    return body

def record(activity, **fields):
    # Queryset update: recording the outcome must not trigger another push.
    Activity.objects.filter(pk=activity.pk).update(**fields)

def push(activity, force=False):
    """Create, update or remove the Google copy to match the activity. Returns the new state."""
    target = family_calendar(activity.household)
    if not activity.google_sync:
        if activity.google_event_id and activity.google_calendar_id:
            remove_remote(activity.google_calendar, activity.google_event_id, activity.title)
        record(activity, google_event_id='', google_etag='', google_state='', google_error='', google_calendar=None)
        return ''
    calendar = activity.google_calendar or (target.calendar if target else None)
    if calendar is None:
        record(activity, google_state='pending', google_error='Set up the family Google calendar to add this activity.')
        return 'pending'
    if activity.google_state == 'conflict' and not force:
        return 'conflict'
    try:
        token = google.access_token(calendar.connection, write=True)
        events = API + '/calendars/' + quote(calendar.external_id, safe='') + '/events'
        body = event_body(activity)
        if activity.google_event_id:
            try:
                result = call('PUT', events + '/' + quote(activity.google_event_id, safe=''), token, body,
                              etag=None if force else activity.google_etag or None)
            except Missing:
                record(activity, google_state='removed', google_error='This event was deleted in Google. Add it again or stop syncing.')
                return 'removed'
            identifier = activity.google_event_id
        else:
            identifier = event_id(activity)
            try:
                result = call('POST', events, token, dict(body, id=identifier))
            except Conflict:
                # An earlier attempt already created it (for example, the reply was lost); update instead.
                result = call('PUT', events + '/' + quote(identifier, safe=''), token, body)
        record(activity, google_calendar=calendar, google_event_id=identifier, google_etag=result.get('etag', ''),
               google_state='synced', google_error='')
        return 'synced'
    except Conflict:
        record(activity, google_state='conflict', google_error='Changed in Google since the last update. Choose which version to keep.')
        return 'conflict'
    except google.GoogleUnavailable as error:
        record(activity, google_calendar=calendar, google_state='failed', google_error=str(error)[:255])
        return 'failed'

def recreate(activity):
    """Add a copy again after it was deleted in Google, under a new event ID."""
    record(activity, google_event_id='', google_etag='', google_state='', google_error='')
    activity.google_event_id, activity.google_etag, activity.google_state = '', '', ''
    target = family_calendar(activity.household)
    calendar = activity.google_calendar or (target.calendar if target else None)
    if calendar is None:
        return push(activity)
    try:
        token = google.access_token(calendar.connection, write=True)
        identifier = event_id(activity, fresh=True)
        events = API + '/calendars/' + quote(calendar.external_id, safe='') + '/events'
        result = call('POST', events, token, dict(event_body(activity), id=identifier))
        record(activity, google_calendar=calendar, google_event_id=identifier, google_etag=result.get('etag', ''), google_state='synced', google_error='')
        return 'synced'
    except google.GoogleUnavailable as error:
        record(activity, google_calendar=calendar, google_state='failed', google_error=str(error)[:255])
        return 'failed'

def remove_remote(calendar, identifier, title):
    """Delete a Google copy now, or keep it queued for retry if Google cannot be reached."""
    pending, _ = GooglePendingDeletion.objects.get_or_create(calendar=calendar, event_id=identifier, defaults={'title': title[:200]})
    try:
        token = google.access_token(calendar.connection, write=True)
        call('DELETE', API + '/calendars/' + quote(calendar.external_id, safe='') + '/events/' + quote(identifier, safe=''), token)
    except Missing:
        pass  # already gone in Google
    except (Conflict, google.GoogleUnavailable) as error:
        GooglePendingDeletion.objects.filter(pk=pending.pk).update(error=str(error)[:255])
        return False
    pending.delete()
    return True

def retry_deletions(household):
    done = 0
    for pending in GooglePendingDeletion.objects.filter(calendar__connection__household=household).select_related('calendar__connection'):
        done += remove_remote(pending.calendar, pending.event_id, pending.title)
    return done

def push_later(pk):
    def run():
        activity = Activity.objects.filter(pk=pk).select_related('household', 'google_calendar__connection').first()
        if activity:
            push(activity)
    transaction.on_commit(run)

@receiver(post_save, sender=Activity)
def activity_saved(sender, instance, raw=False, **kwargs):
    if raw or paused.get():
        return
    if instance.google_sync or instance.google_event_id:
        push_later(instance.pk)

@receiver(post_delete, sender=Activity)
def activity_deleted(sender, instance, **kwargs):
    if paused.get() or not (instance.google_event_id and instance.google_calendar_id):
        return
    calendar = GoogleCalendar.objects.filter(pk=instance.google_calendar_id).select_related('connection').first()
    if calendar is None:
        return
    GooglePendingDeletion.objects.get_or_create(calendar=calendar, event_id=instance.google_event_id, defaults={'title': instance.title[:200]})
    transaction.on_commit(lambda: remove_remote(calendar, instance.google_event_id, instance.title))

def linked_event_ids(household):
    """IDs of Google events written by the app, so the read cache never shows them twice."""
    return set(Activity.objects.filter(household=household).exclude(google_event_id='').values_list('google_event_id', flat=True))
