import json
import uuid
from datetime import timedelta
from functools import wraps
from zoneinfo import ZoneInfo
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection, transaction, DatabaseError
from django.http import JsonResponse, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from .forms import SignInForm, SetupForm, RecordForm, RestoreForm
from .models import BootstrapState, Household, Membership, SetupRecord, RecoveryPoint, RateLimit, JobRun, PendingRestore
from .recovery import MAX_BYTES, replace_household_data, snapshot, validate_any

def limited(bucket, limit=20):
    key = salted_hmac('rate-limit', bucket).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        RateLimit.objects.get_or_create(key=key, defaults={'window_start': now})
        row = RateLimit.objects.select_for_update().get(key=key)
        if row.window_start < now - timedelta(minutes=15):
            row.window_start, row.attempts = now, 0
        row.attempts += 1
        row.save(update_fields=['attempts', 'window_start'])
        return row.attempts > limit

def parent_only(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        membership = Membership.objects.select_related('household').filter(user=request.user, active=True, role='parent').first()
        if not membership:
            raise PermissionDenied('An active parent membership is required.')
        request.household = membership.household
        return view(request, *args, **kwargs)
    return wrapped

@require_GET
def health(request):
    try:
        BootstrapState.objects.exists()
    except DatabaseError:
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})

class SignIn(LoginView):
    template_name = 'sign_in.html'
    authentication_form = SignInForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        email = request.POST.get('username', '')[:254].strip().lower()
        if limited('login-user:' + email) or limited('login-ip:' + request.META.get('REMOTE_ADDR', ''), 200):
            return render(request, 'message.html', {'title': 'Please wait a moment', 'detail': 'Too many sign-in attempts. Try again in 15 minutes.'}, status=429)
        return super().post(request, *args, **kwargs)

@sensitive_post_parameters('token', 'password', 'password_confirm')
@require_http_methods(['GET', 'POST'])
def setup(request):
    if not settings.BOOTSTRAP_TOKEN or not settings.OWNER_EMAIL or BootstrapState.objects.filter(pk=1, used_at__isnull=False).exists():
        return render(request, 'message.html', {'title': 'Setup is closed', 'detail': 'Sign in with your existing parent account.'}, status=403)
    form = SetupForm(request.POST or None)
    if request.method == 'POST':
        if limited('bootstrap:' + request.META.get('REMOTE_ADDR', ''), 10):
            return HttpResponse('Too many attempts. Please try again in 15 minutes.', status=429)
        if form.is_valid():
            data = form.cleaned_data
            email = data['email'].strip().lower()
            if not constant_time_compare(data['token'], settings.BOOTSTRAP_TOKEN) or email != settings.OWNER_EMAIL:
                form.add_error(None, 'The setup code or owner email is incorrect.')
            elif data['password'] != data['password_confirm']:
                form.add_error('password_confirm', 'The passwords do not match.')
            else:
                user = get_user_model()(username=email, email=email, first_name=data['name'])
                try:
                    validate_password(data['password'], user=user)
                except ValidationError as error:
                    form.add_error('password', error)
                if not form.errors:
                    with transaction.atomic():
                        # Serializes first-run setup even when the singleton does not yet exist.
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [47290001])
                        state, _ = BootstrapState.objects.get_or_create(pk=1)
                        if state.used_at or get_user_model().objects.filter(username=email).exists():
                            return HttpResponse('Setup has already completed.', status=409)
                        user.set_password(data['password'])
                        user.save()
                        household = Household.objects.create(name=data['household'])
                        Membership.objects.create(user=user, household=household)
                        state.used_at = timezone.now()
                        state.save(update_fields=['used_at'])
                    login(request, user)
                    return redirect('home')
    return render(request, 'setup.html', {'form': form})

@parent_only
@require_GET
def home(request):
    return render(request, 'home.html', {
        'household': request.household,
        'records': SetupRecord.objects.filter(household=request.household).order_by('-created_at')[:100],
        'form': RecordForm(),
        'last_job': JobRun.objects.filter(status='complete').order_by('-completed_at').first(),
        **backup_context(request.household),
    })

def backup_context(household):
    from django.conf import settings
    from .models import BackupRun
    runs = BackupRun.objects.filter(household=household)
    return {'backup_on': bool(settings.BACKUP_BUCKET), 'last_backup': runs.filter(error='', finished_at__isnull=False).first(),
            'last_backup_attempt': runs.first()}

@parent_only
@require_POST
def records(request):
    form = RecordForm(request.POST)
    if not form.is_valid():
        return render(request, 'message.html', {'title': 'Check the note', 'detail': 'Enter a note between 1 and 200 characters.'}, status=400)
    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=request.household.pk)
        SetupRecord.objects.create(household=household, title=form.cleaned_data['title'])
        household.version += 1
        household.save(update_fields=['version'])
    messages.success(request, 'Note saved to your household.')
    return redirect('foundation')

@parent_only
@require_GET
def export(request):
    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=request.household.pk)
        data = snapshot(household)
        response = JsonResponse(data)
    day = timezone.localdate(timezone=ZoneInfo(household.timezone)).isoformat()
    response['Content-Disposition'] = f'attachment; filename="home-headquarters-household-v2-{day}.json"'
    return response

PREVIEW_LIFETIME = timedelta(hours=1)

def restore_problem(request, title, detail, status):
    request.session.pop('restore_preview', None)
    PendingRestore.objects.filter(household=request.household, created_by=request.user).delete()
    return render(request, 'message.html', {'title': title, 'detail': detail}, status=status)

@parent_only
@require_http_methods(['GET', 'POST'])
def restore(request):
    form = RestoreForm()
    if request.method == 'POST' and request.POST.get('action') == 'preview':
        form = RestoreForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                upload = form.cleaned_data['backup']
                if upload.size > MAX_BYTES:
                    raise ValidationError('The export exceeds the 10 MB limit.')
                data = json.loads(upload.read())
                counts = validate_any(data)
                with transaction.atomic():
                    PendingRestore.objects.filter(household=request.household, created_by=request.user).delete()
                    pending = PendingRestore.objects.create(household=request.household, created_by=request.user,
                                                            household_version=request.household.version, payload=data)
                request.session['restore_preview'] = str(pending.pk)
                return render(request, 'restore.html', {'preview': True, 'counts': counts, 'version': data['version'],
                                                        'export_zone': data['household']['timezone'], 'household': request.household})
            except (ValueError, UnicodeError, ValidationError) as error:
                form.add_error('backup', error if isinstance(error, ValidationError) else 'This file is not valid JSON.')
    elif request.method == 'POST' and request.POST.get('action') == 'apply':
        try:
            pending_id = uuid.UUID(str(request.session.get('restore_preview')))
        except ValueError:
            pending_id = None
        pending = PendingRestore.objects.filter(pk=pending_id, household=request.household, created_by=request.user).first()
        if not pending:
            return HttpResponse('Preview the export before restoring.', status=400)
        if pending.created_at < timezone.now() - PREVIEW_LIFETIME:
            return restore_problem(request, 'This preview expired', 'Preview the export again before restoring.', 400)
        data = pending.payload
        try:
            with transaction.atomic():
                household = Household.objects.select_for_update().get(pk=request.household.pk)
                if household.version != pending.household_version:
                    return restore_problem(request, 'Your household changed', 'Someone saved a change since this preview. Preview the export again before restoring.', 409)
                RecoveryPoint.objects.create(household=household, created_by=request.user, payload=snapshot(household))
                replace_household_data(household, request.user, data)
                household.version += 1
                household.save(update_fields=['version'])
                pending.delete()
        except ValidationError:
            return restore_problem(request, 'This export cannot be restored', 'Nothing was changed. Preview the export again.', 400)
        request.session.pop('restore_preview', None)
        messages.success(request, ('Notes restored.' if data['version'] == 1 else 'Household restored.') + ' A recovery copy was saved before replacement.')
        return redirect('foundation')
    return render(request, 'restore.html', {'form': form})

@parent_only
@require_GET
def recovery_download(request, point_id):
    point = get_object_or_404(RecoveryPoint, pk=point_id, household=request.household)
    response = JsonResponse(point.payload)
    version = point.payload.get('version') if isinstance(point.payload, dict) else 1
    response['Content-Disposition'] = f'attachment; filename="home-headquarters-recovery-v{2 if version == 2 else 1}.json"'
    return response

@parent_only
@require_GET
def recovery_points(request):
    return render(request, 'recovery.html', {'points': RecoveryPoint.objects.filter(household=request.household).order_by('-created_at')[:50]})
