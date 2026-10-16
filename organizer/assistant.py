import uuid
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from django import forms
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from .models import AssistantPlan, AssistantSuggestion, AssistantUsage, Activity, FamilyMember, Task, Household
from .assistant_forms import PromptForm, ClarifyForm, EventDraftForm, TaskDraftForm, json_payload
from .assistant_service import normalized, propose, AssistantUnavailable
from .planner_forms import ActivityForm, TaskForm, has_family_calendar
from .planner import bump, conflict
from .views import parent_only, limited

def reserve_usage(household):
    # Caller holds the household lock. Count attempts, including failures, to bound spend.
    today = timezone.localdate(timezone=ZoneInfo(household.timezone))
    usage, _ = AssistantUsage.objects.get_or_create(household=household, date=today)
    if usage.attempts >= 30:
        return False
    usage.attempts += 1
    usage.save(update_fields=['attempts'])
    return True

def generate(plan):
    generation_version = plan.version
    drafts = list(plan.suggestions.filter(revision=plan.revision).values('kind', 'status', 'payload'))
    try:
        result = propose(plan.household, plan.messages, drafts)
    except AssistantUnavailable as error:
        AssistantPlan.objects.filter(pk=plan.pk, version=generation_version).update(status='error', error=str(error), updated_at=timezone.now())
        return
    with transaction.atomic():
        locked = AssistantPlan.objects.select_for_update().get(pk=plan.pk)
        if locked.version != generation_version or locked.status != 'generating':
            return
        locked.suggestions.filter(status='pending').update(status='superseded')
        locked.revision += 1
        items = ([('event', result['event'])] if result['event'] else []) + [('task', task) for task in result['tasks']]
        # A clarification must not bring back something a parent dismissed earlier in this conversation.
        dismissed = {(item.kind, normalized(item.payload.get('title', ''))) for item in locked.suggestions.filter(status='dismissed')}
        items = [(kind, payload) for kind, payload in items if (kind, normalized(payload['title'])) not in dismissed]
        for position, (kind, payload) in enumerate(items):
            AssistantSuggestion.objects.create(plan=locked, revision=locked.revision, position=position, kind=kind, payload=payload)
        locked.reply, locked.questions = result['reply'], result['questions']
        locked.status, locked.error = 'ready', ''
        locked.version += 1
        locked.save()

@parent_only
@require_http_methods(['GET', 'POST'])
def index(request):
    form = PromptForm(request.POST or None, initial={'request_key': uuid.uuid4()})
    if request.method == 'POST' and form.is_valid():
        key = form.cleaned_data['request_key']
        existing = AssistantPlan.objects.filter(request_key=key).first()
        if existing:
            if existing.household_id != request.household.pk:
                return HttpResponse(status=409)
            return redirect('assistant_plan', pk=existing.pk)
        if limited('assistant:' + str(request.user.pk), 6):
            form.add_error(None, 'Please wait a few minutes before asking again.')
        elif not settings.OPENAI_API_KEY:
            form.add_error(None, 'AI is not configured yet. No plans were created.')
        else:
            with transaction.atomic():
                household = Household.objects.select_for_update().get(pk=request.household.pk)
                existing = AssistantPlan.objects.filter(request_key=key).first()
                if existing:
                    return redirect('assistant_plan', pk=existing.pk) if existing.household_id == household.pk else HttpResponse(status=409)
                if not reserve_usage(household):
                    form.add_error(None, 'The household has reached its 30-request daily preview limit. Try tomorrow.')
                else:
                    prompt = form.cleaned_data['prompt']
                    plan = AssistantPlan.objects.create(household=household, created_by=request.user, request_key=key,
                        title=prompt[:200], messages=[{'role': 'user', 'text': prompt}])
            if not form.errors:
                generate(plan)
                if request.POST.get('origin') == 'home':
                    return redirect(reverse('home') + '#assistant')
                return redirect('assistant_plan', pk=plan.pk)
    return render(request, 'assistant/index.html', {'section': 'assistant', 'form': form,
        'ready': bool(settings.OPENAI_API_KEY), 'plans': AssistantPlan.objects.filter(household=request.household).order_by('-created_at')[:30]})

MORE_OPTIONS = ['reminder_minutes', 'search_prompt', 'search_questions', 'repeat', 'interval', 'weekdays', 'monthly_by', 'ends', 'until', 'count']
REPEAT_LABELS = {'DAILY': 'Repeats daily', 'WEEKLY': 'Repeats weekly', 'MONTHLY': 'Repeats monthly', 'YEARLY': 'Repeats yearly'}

def friendly_time(value):
    try:
        moment = datetime.strptime(value[:5], '%H:%M')
    except (TypeError, ValueError):
        return ''
    return moment.strftime('%I:%M %p').lstrip('0')

def friendly_date(value):
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        return ''
    return f"{day:%a}, {day:%b} {day.day}"

def summarize(suggestion, names):
    """One-line summary and the details still needed, for the compact review card."""
    data = suggestion.payload or {}
    parts, missing = [], []
    if suggestion.kind == 'event':
        parts.append(friendly_date(data.get('start_date')) or 'Date needed')
        if data.get('all_day'):
            parts.append('All day')
        elif data.get('start_time'):
            end = friendly_time(data.get('end_time'))
            assumed = ' (end assumed)' if 'end time' in (data.get('assumed') or []) else ''
            parts.append(friendly_time(data['start_time']) + (f'–{end}{assumed}' if end else ''))
        people = [names[ref] for ref in data.get('participants') or [] if ref in names]
        if people:
            parts.append(', '.join(people))
        if not data.get('start_date'):
            missing.append('date')
        if not data.get('all_day') and not data.get('start_time'):
            missing.append('start time')
        if not data.get('all_day') and not data.get('end_time'):
            missing.append('end time')
    else:
        due = friendly_date(data.get('due_date'))
        parts.append(f'Due {due}' + (f', {friendly_time(data["due_time"])}' if data.get('due_time') else '') if due else 'No deadline')
        parts.append(names.get(data.get('assignee') or '', 'Household'))
        if data.get('high_priority'):
            parts.append('High priority')
    if data.get('repeat') in REPEAT_LABELS:
        parts.append(REPEAT_LABELS[data['repeat']])
    return {'summary': ' · '.join(part for part in parts if part), 'missing': missing}

def stored_data(suggestion):
    """Form data rebuilt from a suggestion's saved draft, for approving without the edit form
    (the Overview quick list). It is validated exactly like edited data."""
    data = QueryDict(mutable=True)
    for key, value in (suggestion.payload or {}).items():
        name = f'{suggestion.pk}-{key}'
        if value is None or value is False or value == '':
            continue
        if isinstance(value, list):
            data.setlist(name, [str(item) for item in value])
        else:
            data[name] = 'on' if value is True else str(value)
    return data

def review_form(suggestion, household, data=None):
    cls = EventDraftForm if suggestion.kind == 'event' else TaskDraftForm
    return cls(data, household=household, initial=suggestion.payload, prefix=str(suggestion.pk))

def approval_form(suggestion, draft_form, household):
    payload = json_payload(draft_form.cleaned_data)
    payload['version'] = 0
    cls = ActivityForm if suggestion.kind == 'event' else TaskForm
    check = cls(payload, household=household, repeat=True)
    valid = check.is_valid()
    if not valid:
        for key, errors in check.errors.items():
            draft_form.add_error(key if key in draft_form.fields else None, errors)
    if suggestion.kind == 'task' and payload.get('reminder_minutes') and not payload.get('due_date'):
        draft_form.add_error('due_date', 'Choose a deadline to save this reminder preference.')
        valid = False
    return check if valid else None

def approve(suggestion, check, draft, plan, user, linked_event):
    item = check.save(commit=False)
    item.household = plan.household
    item.version = 1
    item.reminder_minutes = draft.cleaned_data['reminder_minutes']
    if suggestion.kind == 'event':
        item.timezone = plan.household.timezone
        item.google_sync = has_family_calendar(plan.household)
    else:
        item.activity = linked_event
        item.search_prompt = draft.cleaned_data['search_prompt']
        item.search_questions = draft.cleaned_data['search_questions']
    item.save()
    check.save_m2m()
    suggestion.payload = json_payload(draft.cleaned_data)
    suggestion.status, suggestion.decided_by, suggestion.decided_at = 'approved', user, timezone.now()
    if suggestion.kind == 'event':
        suggestion.activity = item
    else:
        suggestion.task = item
    suggestion.save()
    return item

@parent_only
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    plan = get_object_or_404(AssistantPlan, pk=pk, household=request.household)
    bound = {}
    if request.method == 'POST':
        action = request.POST.get('action', '')
        with transaction.atomic():
            household = Household.objects.select_for_update().get(pk=request.household.pk)
            plan = AssistantPlan.objects.select_for_update().get(pk=pk, household=household)
            suggestions = list(plan.suggestions.filter(revision=plan.revision).select_related('activity', 'task'))
            pending = [item for item in suggestions if item.status == 'pending']
            target = next((item for item in suggestions if action.endswith(':' + str(item.pk))), None)
            # A repeated successful approval is a no-op, including after record deletion.
            chosen = set(request.POST.getlist('selected'))
            if action == 'approve_selected' and not chosen:
                messages.error(request, 'Tick at least one suggestion to add.')
                return redirect('assistant_plan', pk=pk)
            if (action in ('approve_all', 'approve_selected') and not pending) or (action.startswith('approve:') and target and target.status == 'approved'):
                return redirect('assistant_plan', pk=pk)
            if request.POST.get('version') != str(plan.version) or plan.status != 'ready':
                return conflict(request)
            if action.startswith('dismiss:') and target and target.status == 'pending':
                target.status, target.decided_by, target.decided_at = 'dismissed', request.user, timezone.now()
                target.save(update_fields=['status', 'decided_by', 'decided_at'])
                plan.version += 1
                plan.save()
                messages.success(request, 'Suggestion dismissed. No record was created.')
                return redirect('assistant_plan', pk=pk)
            if action == 'approve_all':
                selected = pending
            elif action == 'approve_selected':
                # Activity first (it is drafted at position 0), so tasks added with it are linked to it.
                selected = sorted((item for item in pending if str(item.pk) in chosen), key=lambda item: item.kind != 'event')
            else:
                selected = [target] if target and target.status == 'pending' and action.split(':')[0] in ('approve', 'save') else []
            if not selected:
                return HttpResponse('Choose a current suggestion.', status=400)
            valid, checks = True, {}
            for suggestion in selected:
                posted = any(key.startswith(f'{suggestion.pk}-') for key in request.POST)
                form = review_form(suggestion, household, request.POST if posted else stored_data(suggestion))
                bound[suggestion.pk] = form
                if not form.is_valid():
                    valid = False
                elif action.startswith('save:'):
                    continue
                else:
                    check = approval_form(suggestion, form, household)
                    if check is None:
                        valid = False
                    else:
                        checks[suggestion.pk] = check
            event_suggestion = next((item for item in suggestions if item.kind == 'event'), None)
            if action.startswith('approve:') and target.kind == 'task' and event_suggestion and event_suggestion.status == 'pending':
                bound[target.pk].add_error(None, 'Tick the activity too and use Add selected, so this task is linked to it.')
                valid = False
            if valid:
                linked = event_suggestion.activity if event_suggestion and event_suggestion.status == 'approved' else None
                for suggestion in selected:
                    form = bound[suggestion.pk]
                    if action.startswith('save:'):
                        suggestion.payload = json_payload(form.cleaned_data)
                        suggestion.save(update_fields=['payload'])
                    else:
                        item = approve(suggestion, checks[suggestion.pk], form, plan, request.user, linked)
                        if suggestion.kind == 'event':
                            linked = item
                plan.version += 1
                plan.save()
                bump(household)
                added = len(selected)
                messages.success(request, 'Draft edits saved. Nothing added yet.' if action.startswith('save:') else
                                 f'Added {added} item{"s" if added != 1 else ""} to your plans. Reminder preferences are saved, but notifications are not enabled.')
                if request.POST.get('next') == 'home' and not action.startswith('save:'):
                    return redirect(reverse('home') + '#assistant')
                return redirect('assistant_plan', pk=pk)
    rows = list(plan.suggestions.filter(revision=plan.revision).select_related('activity', 'task'))
    names = {str(member.pk): member.name for member in FamilyMember.objects.filter(household=request.household)}
    review = [{'suggestion': item, 'form': bound.get(item.pk) or review_form(item, request.household), **summarize(item, names)} for item in rows]
    can_revise = not plan.suggestions.filter(status='approved').exists() and (plan.status != 'generating' or plan.updated_at < timezone.now() - timedelta(minutes=2))
    conflicts = []
    for item in rows:
        if item.kind == 'event' and item.status == 'pending' and item.payload.get('start_date'):
            day = item.payload['start_date']
            try:
                from .recurrence import household_events
                conflicts.extend(household_events(request.household, date.fromisoformat(day), date.fromisoformat(day))[:10])
            except ValueError:
                pass
            from .google_service import shared_events
            conflicts.extend(shared_events(request.household, day, day)[:10])
    return render(request, 'assistant/review.html', {'section': 'assistant', 'plan': plan, 'review': review,
        'history': plan.suggestions.exclude(revision=plan.revision).order_by('-revision', 'position'),
        'has_pending': any(item.status == 'pending' for item in rows), 'has_added': any(item.status == 'approved' for item in rows), 'can_revise': can_revise,
        'clarify': ClarifyForm(initial={'version': plan.version}), 'conflicts': conflicts, 'more_options': MORE_OPTIONS,
        'zone': request.household.timezone})

@parent_only
@require_POST
def revise(request, pk):
    form = ClarifyForm(request.POST)
    retry = request.POST.get('retry') == '1'
    if not retry and not form.is_valid():
        messages.error(request, 'Please add details (up to 2,000 characters).')
        return redirect('assistant_plan', pk=pk)
    if limited('assistant:' + str(request.user.pk), 6):
        return HttpResponse('Please wait a few minutes before asking again.', status=429)
    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=request.household.pk)
        plan = get_object_or_404(AssistantPlan.objects.select_for_update(), pk=pk, household=household)
        if request.POST.get('version') != str(plan.version) or plan.suggestions.filter(status='approved').exists():
            return conflict(request)
        if plan.status == 'generating' and plan.updated_at > timezone.now() - timedelta(minutes=2):
            return HttpResponse('This proposal is still being prepared. Refresh shortly.', status=409)
        if len(plan.messages) >= 10 or not reserve_usage(household):
            messages.error(request, 'This conversation or today’s request limit has been reached. Start a new conversation tomorrow if needed.')
            return redirect('assistant_plan', pk=pk)
        if not retry:
            plan.messages = plan.messages + [{'role': 'assistant', 'text': plan.reply, 'questions': plan.questions}, {'role': 'user', 'text': form.cleaned_data['answer']}]
        plan.status, plan.error = 'generating', ''
        plan.version += 1
        plan.save()
    generate(plan)
    return redirect('assistant_plan', pk=pk)

class SearchForm(forms.Form):
    query = forms.CharField(max_length=500, label='Search prompt', widget=forms.Textarea(attrs={'rows': 3}))
    version = forms.IntegerField(widget=forms.HiddenInput)

@parent_only
@require_http_methods(['GET', 'POST'])
def task_search(request, pk):
    task = get_object_or_404(Task, pk=pk, household=request.household)
    form = SearchForm(request.POST or None, initial={'query': task.search_prompt, 'version': task.version})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            Household.objects.select_for_update().get(pk=request.household.pk)
            task = Task.objects.select_for_update().get(pk=pk, household=request.household)
            if task.version != form.cleaned_data['version']:
                return conflict(request)
            task.search_prompt = form.cleaned_data['query']
            task.version += 1
            task.save(update_fields=['search_prompt', 'version'])
        # User explicitly submits a reviewable query. A redirect is not a completed search.
        return redirect('https://www.google.com/search?' + urlencode({'q': task.search_prompt}))
    return render(request, 'assistant/search.html', {'section': 'tasks', 'task': task, 'form': form})
