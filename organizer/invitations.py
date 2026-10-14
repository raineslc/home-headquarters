import hashlib
import secrets
from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from .models import Household, Membership, ParentInvitation
from .views import parent_only, limited

class InviteForm(forms.Form):
    email = forms.EmailField(label="Other parent's email", max_length=150)

class JoinForm(forms.Form):
    name = forms.CharField(max_length=100, label='Your name')
    password = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password_confirm = forms.CharField(label='Confirm password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

@parent_only
@require_http_methods(['GET', 'POST'])
def index(request):
    form = InviteForm(request.POST or None)
    invitation_link = None
    if request.method == 'POST' and form.is_valid():
        if limited('invite:' + str(request.user.pk), 10):
            return HttpResponse('Please wait before creating another invitation.', status=429)
        email = form.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(username=email).exists():
            form.add_error('email', 'This email already has a parent account. Ask them to sign in.')
        else:
            token = secrets.token_urlsafe(32)
            with transaction.atomic():
                Household.objects.select_for_update().get(pk=request.household.pk)
                ParentInvitation.objects.filter(household=request.household, email=email, used_at__isnull=True).delete()
                ParentInvitation.objects.create(household=request.household, created_by=request.user, email=email,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(days=2))
            invitation_link = request.build_absolute_uri(reverse('parent_join') + '?invite=' + token)
    return render(request, 'connections/parents.html', {'section': 'settings', 'form': form, 'invitation_link': invitation_link,
        'memberships': Membership.objects.filter(household=request.household, active=True).select_related('user'),
        'invitations': ParentInvitation.objects.filter(household=request.household, used_at__isnull=True, expires_at__gt=timezone.now())})

@parent_only
@require_POST
def cancel(request, pk):
    invitation = get_object_or_404(ParentInvitation, pk=pk, household=request.household)
    invitation.delete()
    messages.success(request, 'Invitation cancelled.')
    return redirect('parents')

@sensitive_post_parameters('password', 'password_confirm')
@require_http_methods(['GET', 'POST'])
def join(request):
    # Remove the bearer invitation from the URL before showing a form or loading assets.
    if 'invite' in request.GET:
        request.session['parent_invite_hash'] = hashlib.sha256(request.GET['invite'].encode()).hexdigest()
        response = redirect('parent_join')
        response['Referrer-Policy'] = 'no-referrer'
        return response
    invitation = ParentInvitation.objects.filter(token_hash=request.session.get('parent_invite_hash', ''),
        used_at__isnull=True, expires_at__gt=timezone.now()).select_related('household').first()
    if not invitation:
        return render(request, 'message.html', {'title': 'Invitation unavailable', 'detail': 'Ask your partner for a new invitation. Links expire after two days and can only be used once.'}, status=400)
    if request.user.is_authenticated:
        return render(request, 'message.html', {'title': 'Use your own parent account', 'detail': 'Sign out first, or open the invitation in your own browser to create your separate sign-in.'}, status=409)
    form = JoinForm(request.POST or None)
    if request.method == 'POST':
        if limited('join:' + request.META.get('REMOTE_ADDR', ''), 20):
            return HttpResponse('Please wait before trying again.', status=429)
        if form.is_valid():
            user = get_user_model()(username=invitation.email, email=invitation.email, first_name=form.cleaned_data['name'])
            if form.cleaned_data['password'] != form.cleaned_data['password_confirm']:
                form.add_error('password_confirm', 'The passwords do not match.')
            try:
                validate_password(form.cleaned_data['password'], user)
            except ValidationError as error:
                form.add_error('password', error)
            if not form.errors:
                with transaction.atomic():
                    Household.objects.select_for_update().get(pk=invitation.household_id)
                    invitation = ParentInvitation.objects.select_for_update().filter(pk=invitation.pk, used_at__isnull=True, expires_at__gt=timezone.now()).first()
                    if not invitation or get_user_model().objects.filter(username=user.username).exists():
                        return HttpResponse('Invitation no longer available. Ask for a new invitation.', status=409)
                    user.set_password(form.cleaned_data['password'])
                    user.save()
                    Membership.objects.create(household=invitation.household, user=user)
                    invitation.used_at = timezone.now()
                    invitation.save(update_fields=['used_at'])
                request.session.pop('parent_invite_hash', None)
                login(request, user)
                return redirect('google_connections')
    return render(request, 'connections/join.html', {'form': form, 'invitation': invitation})
