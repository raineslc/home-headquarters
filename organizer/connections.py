import hashlib
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
from .models import GoogleConnection, GoogleCalendar, GoogleEvent
from .views import parent_only, limited

@parent_only
@require_GET
def index(request):
    return render(request, 'connections/index.html', {'section': 'settings', 'ready': google.configured(),
        'connections': GoogleConnection.objects.filter(household=request.household, owner=request.user).prefetch_related('calendars'),
        'shared': GoogleCalendar.objects.filter(connection__household=request.household).exclude(visibility='off').select_related('connection__owner')})

@parent_only
@require_POST
def begin(request):
    if not google.configured():
        messages.error(request, 'Google connection setup is still required. No Google account has been connected.')
        return redirect('google_connections')
    if limited('google-connect:' + str(request.user.pk), 10):
        return HttpResponse('Please wait 15 minutes before trying again.', status=429)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    request.session['google_oauth'] = {'state': state, 'verifier': verifier,
        'user': request.user.pk, 'household': str(request.household.pk), 'expires': (timezone.now() + timedelta(minutes=10)).timestamp()}
    oauth = google.flow(state=state, code_verifier=verifier)
    url, _ = oauth.authorization_url(access_type='offline', prompt='consent select_account')
    return redirect(url)

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
        oauth = google.flow(state=pending['state'], code_verifier=pending['verifier'])
        oauth.fetch_token(code=request.GET['code'], timeout=20)
        credentials = oauth.credentials
        granted = credentials.granted_scopes or credentials.scopes
        if not set(google.SCOPES).issubset(set(granted)):
            raise google.GoogleUnavailable('Google did not grant the required read-only calendar permissions. Please connect again and allow both calendar permissions.')
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
            connection.version += 1
            connection.save()
        google.refresh_calendars(connection, credentials.token)
        messages.success(request, 'Google connected. Choose calendars and how much to share below; new calendars are hidden until you choose.')
    except (google.GoogleUnavailable, OAuth2Error, requests.RequestException, ValueError) as error:
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
