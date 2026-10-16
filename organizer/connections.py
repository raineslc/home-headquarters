import hashlib
import logging
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_GET, require_POST
from oauthlib.oauth2 import OAuth2Error
import requests
from . import google_service as google
from . import google_writes
from .models import Activity, FamilyCalendar, GoogleConnection, GoogleCalendar, GoogleEvent, GooglePendingDeletion
from .views import parent_only, limited

logger = logging.getLogger('organizer.google')

@parent_only
@require_GET
def index(request):
    return render(request, 'connections/index.html', {'section': 'settings', 'ready': google.configured(),
        'connections': GoogleConnection.objects.filter(household=request.household, owner=request.user).prefetch_related('calendars'),
        'shared': GoogleCalendar.objects.filter(connection__household=request.household).exclude(visibility='off').select_related('connection__owner'),
        'family': google_writes.family_calendar(request.household),
        'pending_deletions': GooglePendingDeletion.objects.filter(calendar__connection__household=request.household),
        'waiting': Activity.objects.filter(household=request.household, google_sync=True).exclude(google_state__in=['synced', 'conflict', 'removed']).count(),
        'attention': Activity.objects.filter(household=request.household, google_sync=True, google_state__in=['conflict', 'removed'])})

def start_oauth(request, write=False, login_hint=None):
    if not google.configured():
        messages.error(request, 'Google connection setup is still required. No Google account has been connected.')
        return redirect('google_connections')
    if limited('google-connect:' + str(request.user.pk), 10):
        return HttpResponse('Please wait 15 minutes before trying again.', status=429)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    request.session['google_oauth'] = {'state': state, 'verifier': verifier, 'write': write,
        'user': request.user.pk, 'household': str(request.household.pk), 'expires': (timezone.now() + timedelta(minutes=10)).timestamp()}
    oauth = google.flow(write=write, state=state, code_verifier=verifier)
    # Keep permissions granted earlier, so reconnecting never drops family calendar access.
    extra = {'login_hint': login_hint} if login_hint else {}
    url, _ = oauth.authorization_url(access_type='offline', prompt='consent select_account', include_granted_scopes='true', **extra)
    return redirect(url)

@parent_only
@require_POST
def begin(request):
    return start_oauth(request)

@parent_only
@require_POST
def family_begin(request, pk):
    # Opt-in: asks only this parent for the extra "calendars this app creates" permission.
    connection = owned(request, pk)
    if google_writes.family_calendar(request.household):
        messages.info(request, 'The family Google calendar is already set up.')
        return redirect('google_connections')
    return start_oauth(request, write=True, login_hint=connection.email)

@parent_only
@require_GET
def callback(request):
    pending = request.session.pop('google_oauth', None)
    if not pending or pending['user'] != request.user.pk or pending['household'] != str(request.household.pk) or pending['expires'] < timezone.now().timestamp() or not constant_time_compare(pending['state'], request.GET.get('state', '')):
        messages.error(request, 'This connection request expired or was already used. Please connect again.')
        return redirect('google_connections')
    if request.GET.get('error') or not request.GET.get('code'):
        messages.info(request, 'Google connection was cancelled. Nothing was shared.')
        return redirect('google_connections')
    try:
        write = bool(pending.get('write'))
        oauth = google.flow(write=write, state=pending['state'], code_verifier=pending['verifier'])
        oauth.fetch_token(code=request.GET['code'], timeout=20)
        credentials = oauth.credentials
        granted = credentials.granted_scopes or credentials.scopes
        if not set(google.SCOPES).issubset(set(granted)):
            raise google.GoogleUnavailable('Google did not grant the required read-only calendar permissions. Please connect again and allow both calendar permissions.')
        if write and google.WRITE_SCOPE not in granted:
            raise google.GoogleUnavailable('Google did not grant permission to create the family calendar. Nothing was changed; your read-only connection still works.')
        identity = google.get_json('https://openidconnect.googleapis.com/v1/userinfo', credentials.token)
        if not identity.get('email_verified') or not identity.get('sub') or not identity.get('email'):
            raise google.GoogleUnavailable('Google could not verify this account.')
        with transaction.atomic():
            # Serialize account ownership as well as repeated OAuth callbacks.
            from .models import Household
            Household.objects.select_for_update().get(pk=request.household.pk)
            connection = GoogleConnection.objects.filter(household=request.household, subject=identity['sub']).first()
            if connection and connection.owner_id != request.user.pk:
                raise google.GoogleUnavailable('This Google account is already linked by the other parent. Each parent should connect their own account.')
            if not connection:
                connection = GoogleConnection(household=request.household, owner=request.user, subject=identity['sub'])
            if credentials.refresh_token:
                connection.encrypted_refresh_token = google.cipher().encrypt(credentials.refresh_token.encode()).decode()
            if not connection.encrypted_refresh_token:
                raise google.GoogleUnavailable('Google did not provide continuing access. Please connect again.')
            connection.email, connection.needs_reconnect = identity['email'], False
            connection.can_write = google.WRITE_SCOPE in granted
            connection.version += 1
            connection.save()
        if write:
            if not google_writes.family_calendar(request.household):
                google_writes.create_family_calendar(connection, credentials.token)
            google.refresh_calendars(connection, credentials.token)
            messages.success(request, 'The Home Headquarters calendar was created in your Google account. Activities you choose will be added to it.')
        else:
            google.refresh_calendars(connection, credentials.token)
            messages.success(request, 'Google connected. Choose calendars and how much to share below; new calendars are hidden until you choose.')
    except (google.GoogleUnavailable, OAuth2Error, requests.RequestException, ValueError) as error:
        # Log only the error type and Google's short error code (for example invalid_client);
        # never tokens, codes from the URL, or provider response bodies.
        code = getattr(error, 'error', '') if isinstance(error, OAuth2Error) else ''
        logger.warning('Google connection failed: %s %s', type(error).__name__, code if isinstance(code, str) and code.isidentifier() else '')
        messages.error(request, str(error) if isinstance(error, google.GoogleUnavailable) else 'Google connection could not finish. Please try again.')
    return redirect('google_connections')

def owned(request, pk):
    return get_object_or_404(GoogleConnection, pk=pk, household=request.household, owner=request.user)

@parent_only
@require_POST
def choices(request, pk):
    connection = owned(request, pk)
    with transaction.atomic():
        connection = GoogleConnection.objects.select_for_update().get(pk=connection.pk)
        if str(connection.version) != request.POST.get('version'):
            return HttpResponse('Calendar choices changed. Reload this page before saving.', status=409)
        calendars = list(connection.calendars.all())
        for calendar in calendars:
            visibility = request.POST.get('visibility_' + str(calendar.pk), 'off')
            color = request.POST.get('color_' + str(calendar.pk), 'blue')
            if visibility not in ('off', 'busy', 'details') or color not in google.COLORS:
                return HttpResponse('Choose a valid sharing option and color.', status=400)
        for calendar in calendars:
            visibility = request.POST.get('visibility_' + str(calendar.pk), 'off')
            if visibility == 'off':
                calendar.events.all().delete()
            elif visibility == 'busy':
                calendar.events.update(title='Busy', location='', html_link='')
            if visibility != calendar.visibility:
                calendar.last_synced = None
            calendar.visibility = visibility
            calendar.color = request.POST.get('color_' + str(calendar.pk), 'blue')
            calendar.save()
        connection.version += 1
        connection.save(update_fields=['version'])
    messages.success(request, 'Sharing choices saved. Use Sync now to bring in the latest events.')
    return redirect('google_connections')

@parent_only
@require_POST
def sync(request, pk):
    connection = owned(request, pk)
    if limited('google-sync:' + str(connection.pk), 15):
        return HttpResponse('Too many sync attempts. Please wait 15 minutes.', status=429)
    try:
        google.refresh_calendars(connection)
        connection.refresh_from_db()
        google.sync_connection(connection)
        messages.success(request, 'Your selected Google calendars are up to date.')
    except google.GoogleUnavailable as error:
        if isinstance(error, google.ReconnectRequired):
            GoogleConnection.objects.filter(pk=connection.pk).update(needs_reconnect=True)
        messages.error(request, str(error))
    return redirect('google_connections')

@parent_only
@require_POST
def disconnect(request, pk):
    connection = owned(request, pk)
    with transaction.atomic():
        connection = GoogleConnection.objects.select_for_update().get(pk=connection.pk)
        if str(connection.version) != request.POST.get('version'):
            return HttpResponse('Connection changed. Reload before disconnecting.', status=409)
        connection.delete()
    messages.success(request, 'Connection and its saved Google events removed from Home Headquarters. Your Google events were not changed. You can also remove app access in your Google Account permissions.')
    return redirect('google_connections')

@parent_only
@require_GET
def event_detail(request, pk):
    event = get_object_or_404(GoogleEvent, pk=pk, calendar__connection__household=request.household,
        calendar__visibility__in=['busy', 'details'], calendar__connection__owner__membership__active=True,
        calendar__connection__owner__membership__household=request.household)
    return render(request, 'connections/event.html', {'section': 'home', 'event': event})

@parent_only
@require_POST
def family_retry(request):
    removed = google_writes.retry_deletions(request.household)
    waiting = Activity.objects.filter(household=request.household, google_sync=True).exclude(google_state__in=['synced', 'conflict', 'removed'])
    results = [google_writes.push(activity) for activity in waiting.select_related('household', 'google_calendar__connection')[:50]]
    left = GooglePendingDeletion.objects.filter(calendar__connection__household=request.household).count() + results.count('failed') + results.count('pending')
    if left:
        messages.error(request, f'{left} Google update(s) still need attention. Try again shortly.')
    else:
        messages.success(request, 'Google is up to date.')
    if removed:
        messages.info(request, f'Removed {removed} deleted activit{"y" if removed == 1 else "ies"} from Google.')
    return redirect('google_connections')

@parent_only
@require_POST
def family_stop(request):
    # Stops future updates and leaves existing Google events untouched; nothing is deleted in Google.
    with transaction.atomic():
        from .models import Household
        Household.objects.select_for_update().get(pk=request.household.pk)
        Activity.objects.filter(household=request.household).update(google_sync=False, google_calendar=None, google_event_id='',
                                                                    google_etag='', google_state='', google_error='')
        FamilyCalendar.objects.filter(household=request.household).delete()
    messages.success(request, 'Home Headquarters will no longer update Google. Existing Google events were left as they are.')
    return redirect('google_connections')

@parent_only
@require_POST
def activity_google(request, pk):
    activity = get_object_or_404(Activity.objects.select_related('household', 'google_calendar__connection'), pk=pk, household=request.household)
    action = request.POST.get('action')
    if action == 'retry':
        state = google_writes.push(activity)
    elif action == 'keep_app':
        state = google_writes.push(activity, force=True)
    elif action == 'recreate':
        state = google_writes.recreate(activity)
    elif action == 'unlink':
        # Keep whatever is in Google now and stop updating it from here.
        Activity.objects.filter(pk=activity.pk).update(google_sync=False, google_calendar=None, google_event_id='', google_etag='', google_state='', google_error='')
        messages.success(request, 'This activity will no longer update Google. The Google event was left as it is.')
        return redirect('activity_detail', pk=pk)
    else:
        return HttpResponse('Choose a Google action.', status=400)
    if state == 'synced':
        messages.success(request, 'Google Calendar is up to date for this activity.')
    else:
        messages.error(request, Activity.objects.get(pk=pk).google_error or 'Google could not be updated. Try again shortly.')
    return redirect('activity_detail', pk=pk)

