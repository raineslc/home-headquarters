import calendar
import uuid
from django.conf import settings as app_settings
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .models import Activity, FamilyMember, Household, LunchPlan, Task
from .planner_forms import ActivityForm, MemberForm, TaskForm, QuickActivityForm, QuickTaskForm
from .views import parent_only
from .google_service import shared_events
from .models import GoogleCalendar
from .recurrence import describe, end_before, first_on_or_after, household_events, next_date, occurrence_of

def chosen_date(request):
    try:
        day = date.fromisoformat(request.GET.get('date', ''))
        if not 1901 <= day.year <= 2098:
            raise ValueError
        return day
    except ValueError:
        return timezone.localdate(timezone=ZoneInfo(request.household.timezone))

def conflict(request):
    return render(request, 'message.html', {'title': 'Someone updated this plan', 'detail': 'Your changes were not saved. Open the latest version and try again so neither parent loses an edit.'}, status=409)

def version_matches(request, item):
    try:
        return int(request.POST.get('version', '-1')) == item.version
    except ValueError:
        return False

def bump(household):
    household.version += 1
    household.save(update_fields=['version'])

def lunch_rows(household, days):
    plans = {(x.child_id, x.date): x for x in LunchPlan.objects.filter(household=household, date__in=days)}
    rows = []
    for child in FamilyMember.objects.filter(household=household, role='child', archived=False).order_by('name'):
        rows.append({'child': child, 'cells': [{'date': day, 'choice': plans[(child.id, day)].choice if (child.id, day) in plans else 'undecided', 'label': plans[(child.id, day)].get_choice_display() if (child.id, day) in plans else 'Not decided'} for day in days]})
    return rows

def quick_entry(request, task_page=False):
    kind = request.POST.get('quick_kind') if request.method == 'POST' else None
    activity_form = QuickActivityForm(request.POST if kind == 'activity' else None, household=request.household, prefix='activity', initial={'start_date': chosen_date(request)})
    task_form = QuickTaskForm(request.POST if kind == 'task' else None, household=request.household, prefix='task')
    context = {'quick_activity': activity_form, 'quick_task': task_form}
    if request.method != 'POST':
        return context, None
    if kind not in (('task',) if task_page else ('activity', 'task')):
        return context, HttpResponse('Choose an activity or task.', status=400)
    form = activity_form if kind == 'activity' else task_form
    if form.is_valid():
        with transaction.atomic():
            household = Household.objects.select_for_update().get(pk=request.household.pk)
            item = form.save(commit=False)
            item.household = household
            item.version = 1
            if kind == 'activity':
                item.end_date = item.start_date
                item.timezone = household.timezone
            item.save()
            form.save_m2m()
            bump(household)
        messages.success(request, 'Activity added. Open it on the calendar to add more details.' if kind == 'activity' else 'Task added.')
        target = reverse('tasks') if task_page else reverse('home')
        if kind == 'activity':
            target += '?date=' + item.start_date.isoformat()
        elif request.GET.get('date'):
            target += '?date=' + chosen_date(request).isoformat()
        return context, redirect(target)
    return context, None

@parent_only
@require_http_methods(['GET', 'POST'])
def dashboard(request):
    quick_context, response = quick_entry(request)
    quick_context['assistant_request_key'] = uuid.uuid4()
    quick_context['assistant_ready'] = bool(app_settings.OPENAI_API_KEY)
    if response is not None:
        return response
    day = chosen_date(request)
    today = timezone.localdate(timezone=ZoneInfo(request.household.timezone))
    mode = request.GET.get('view', 'week')
    if mode not in ('week', 'month', 'agenda'):
        mode = 'week'
    monday = day - timedelta(days=day.weekday())
    # Agenda is a rolling seven-day Upcoming list from the chosen date; week and month align to the calendar.
    first = day.replace(day=1) if mode == 'month' else day if mode == 'agenda' else monday
    start = first - timedelta(days=first.weekday()) if mode == 'month' else first
    count = 42 if mode == 'month' else 7
    days = [start + timedelta(days=i) for i in range(count)]
    end = days[-1]
    events = household_events(request.household, start, end)
    events += shared_events(request.household, start, end)
    events.sort(key=lambda event: (event.start_date, event.start_time.isoformat() if event.start_time else '', event.title))
    task_query = Task.objects.filter(household=request.household).select_related('assignee', 'activity')
    due_tasks = sorted(task_query.filter(completed_at__isnull=True, due_date__range=(start, end)), key=lambda t: (not t.high_priority, t.due_time is None, t.due_time or time(), t.title))
    overdue = list(task_query.filter(completed_at__isnull=True, due_date__lt=today)) if mode == 'agenda' and start <= today <= end else []
    school_lunches = list(LunchPlan.objects.filter(household=request.household, date__range=(start, end), choice='school', child__household=request.household, child__role='child', child__archived=False).select_related('child').order_by('child__name'))
    cells = [{'date': d, 'today': d == today, 'in_month': d.month == day.month, 'events': [e for e in events if e.start_date <= d <= e.end_date], 'tasks': [t for t in due_tasks if t.due_date == d], 'school_lunches': [lunch for lunch in school_lunches if lunch.date == d]} for d in days]
    priorities = task_query.filter(completed_at__isnull=True).filter(Q(due_date__lte=monday + timedelta(days=6)) | Q(due_date__isnull=True) | Q(high_priority=True)).order_by('-high_priority', 'due_date', 'title')[:8]
    today_events = household_events(request.household, today, today) + shared_events(request.household, today, today)
    today_events.sort(key=lambda event: (event.start_time.isoformat() if event.start_time else '', event.title))
    quick_context['google_calendars'] = GoogleCalendar.objects.filter(connection__household=request.household, connection__owner__membership__active=True, connection__owner__membership__household=request.household).exclude(visibility='off').select_related('connection')
    if mode == 'month':
        previous = (first - timedelta(days=1)).replace(day=1)
        next_day = (first + timedelta(days=32)).replace(day=1)
    else:
        previous, next_day = day - timedelta(days=7), day + timedelta(days=7)
    return render(request, 'planner/dashboard.html', {**quick_context, 'section': 'home', 'day': day, 'today': today, 'mode': mode, 'cells': cells, 'previous': previous, 'next': next_day, 'week_start': monday, 'week_end': monday + timedelta(days=6), 'range_end': end, 'overdue': overdue, 'priorities': priorities, 'today_events': today_events, 'today_tasks': task_query.filter(completed_at__isnull=True, due_date=today), 'packed': LunchPlan.objects.filter(household=request.household, date=today, choice='pack', child__archived=False).select_related('child')})

@parent_only
@require_GET
def family(request):
    return render(request, 'planner/family.html', {'section': 'family', 'members': FamilyMember.objects.filter(household=request.household).order_by('archived', 'role', 'name')})

@parent_only
@require_http_methods(['GET', 'POST'])
def tasks(request):
    quick_context, response = quick_entry(request, task_page=True)
    if response is not None:
        return response
    status = request.GET.get('status', 'open')
    query = Task.objects.filter(household=request.household).select_related('assignee', 'activity')
    if status != 'all':
        query = query.filter(completed_at__isnull=status != 'done')
    return render(request, 'planner/tasks.html', {**quick_context, 'section': 'tasks', 'tasks': query, 'status': status, 'today': timezone.localdate(timezone=ZoneInfo(request.household.timezone))})

@parent_only
@require_GET
def activity_detail(request, pk):
    series = get_object_or_404(Activity.objects.prefetch_related('participants'), pk=pk, household=request.household)
    item = requested_occurrence(request, series)
    return render(request, 'planner/activity.html', {'section': 'home', 'item': item, 'series': series, 'repeats': describe(series.recurrence, series.start_date),
                                                     'occurrence': getattr(item, 'instance_date', None), 'tasks': series.tasks.select_related('assignee').all()})

def requested_occurrence(request, series):
    """The occurrence named by ?occurrence= (or a hidden POST field); the activity itself when none is named."""
    value = request.POST.get('occurrence') or request.GET.get('occurrence')
    if not value:
        return series
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise Http404('Unknown occurrence')
    occurrence = occurrence_of(series, day)
    if occurrence is None:
        raise Http404('Unknown occurrence')
    return occurrence

def shift_dates(values, delta):
    return [(date.fromisoformat(value) + delta).isoformat() for value in values]

def next_task(task):
    """Create the following task in a repeating series once; returns it, or None when the series ended."""
    if not (task.recurrence and task.series_key and task.recurrence_start and task.due_date):
        return None
    due = next_date(task.recurrence, task.recurrence_start, task.due_date)
    if due is None:
        return None
    following, _ = Task.objects.get_or_create(series_key=task.series_key, due_date=due, defaults={
        'household': task.household, 'title': task.title, 'high_priority': task.high_priority, 'assignee': task.assignee,
        'activity': task.activity, 'due_time': task.due_time, 'notes': task.notes, 'reminder_minutes': task.reminder_minutes,
        'search_prompt': task.search_prompt, 'search_questions': task.search_questions, 'recurrence': task.recurrence,
        'recurrence_start': task.recurrence_start})
    return following

@parent_only
@require_http_methods(['GET', 'POST'])
def edit(request, kind, pk=None):
    config = {'activity': (Activity, ActivityForm, 'activity'), 'task': (Task, TaskForm, 'task'), 'member': (FamilyMember, MemberForm, 'family member')}
    if kind not in config:
        return HttpResponse(status=404)
    model, form_class, label = config[kind]
    instance = get_object_or_404(model, pk=pk, household=request.household) if pk else None
    if kind == 'activity' and instance and instance.recurrence and (request.GET.get('occurrence') or request.POST.get('occurrence')):
        return edit_occurrence(request, instance)
    initial = {}
    if not pk and kind == 'activity':
        initial = {'start_date': chosen_date(request), 'end_date': chosen_date(request)}
    if not pk and kind == 'task' and request.GET.get('activity'):
        linked = get_object_or_404(Activity, pk=request.GET['activity'], household=request.household)
        initial['activity'] = linked.pk
    repeat = kind == 'task' or kind == 'activity' and not (instance and instance.series_id)
    extra = {'repeat': repeat} if kind != 'member' else {}
    form = form_class(request.POST or None, instance=instance, household=request.household, initial=initial, **extra)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            household = Household.objects.select_for_update().get(pk=request.household.pk)
            if pk:
                latest = model.objects.select_for_update().get(pk=pk, household=household)
                if form.cleaned_data['version'] != latest.version:
                    return conflict(request)
            item = form.save(commit=False)
            item.household = household
            item.version = latest.version + 1 if pk else 1
            if kind == 'activity':
                item.timezone = household.timezone
            item.save()
            form.save_m2m()
            bump(household)
        messages.success(request, f'{label.capitalize()} saved.')
        return redirect('activity_detail', pk=item.pk) if kind == 'activity' else redirect('tasks' if kind == 'task' else 'family')
    return render(request, 'planner/edit.html', {'section': 'family' if kind == 'member' else 'tasks' if kind == 'task' else 'home', 'form': form, 'label': label, 'item': instance, 'kind': kind, 'zone': request.household.timezone})

SCOPES = {'one': 'Only this occurrence', 'following': 'This and following occurrences', 'all': 'All occurrences'}

def chosen_scope(request):
    scope = request.POST.get('scope', 'one')
    return scope if scope in SCOPES else 'one'

def edit_occurrence(request, series):
    occurrence = requested_occurrence(request, series)
    day = occurrence.instance_date
    scope = chosen_scope(request) if request.method == 'POST' else 'one'
    if scope == 'following' and day == series.start_date:
        scope = 'all'
    initial = {'start_date': occurrence.start_date, 'end_date': occurrence.end_date, 'start_time': occurrence.start_time, 'end_time': occurrence.end_time}
    if request.method == 'POST':
        # 'one' and 'following' save a new Activity; 'all' edits the series itself.
        form = ActivityForm(request.POST, instance=series if scope == 'all' else None, household=request.household, repeat=scope != 'one',
                            realign={'all': 'skip', 'following': 'forward'}.get(scope, ''))
    else:
        form = ActivityForm(instance=series, household=request.household, initial=initial, repeat=True)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            household = Household.objects.select_for_update().get(pk=request.household.pk)
            latest = Activity.objects.select_for_update().get(pk=series.pk, household=household)
            if form.cleaned_data['version'] != latest.version or occurrence_of(latest, day) is None:
                return conflict(request)
            if scope == 'all':
                # Moving one occurrence's date moves the whole series by the same amount.
                delta = form.cleaned_data['start_date'] - day
                span = form.cleaned_data['end_date'] - form.cleaned_data['start_date']
                item = form.save(commit=False)
                item.start_date = latest.start_date + delta
                if item.recurrence:
                    # A changed pattern may not include the shifted first date; start at its first match.
                    item.start_date = first_on_or_after(item.recurrence, item.start_date) or item.start_date
                item.end_date = item.start_date + span
                item.recurrence_exdates = shift_dates(latest.recurrence_exdates, delta)
                if delta:
                    for override in latest.overrides.all():
                        override.occurrence_date += delta
                        override.save(update_fields=['occurrence_date'])
                item.version = latest.version + 1
                item.timezone = household.timezone
                item.save()
                form.save_m2m()
            else:
                if scope == 'one':
                    latest.recurrence_exdates = latest.recurrence_exdates + [day.isoformat()]
                else:
                    latest.recurrence = end_before(latest.recurrence, latest.start_date, day)
                    latest.overrides.filter(occurrence_date__gte=day).delete()
                latest.version += 1
                latest.save(update_fields=['recurrence', 'recurrence_exdates', 'version'])
                item = form.save(commit=False)
                item.household = household
                item.timezone = household.timezone
                item.version = 1
                if scope == 'one':
                    item.series, item.occurrence_date, item.recurrence = latest, day, ''
                item.save()
                form.save_m2m()
            bump(household)
        messages.success(request, {'one': 'This occurrence was saved.', 'following': 'This and following occurrences were saved.', 'all': 'All occurrences were saved.'}[scope])
        return redirect('activity_detail', pk=item.pk)
    return render(request, 'planner/edit.html', {'section': 'home', 'form': form, 'label': 'activity', 'item': series, 'kind': 'activity', 'zone': request.household.timezone,
                                                 'occurrence': day, 'scopes': SCOPES, 'scope': scope, 'repeats': describe(series.recurrence, series.start_date)})

@parent_only
@require_http_methods(['GET', 'POST'])
def remove(request, kind, pk):
    model = {'activity': Activity, 'task': Task, 'member': FamilyMember}.get(kind)
    if not model:
        return HttpResponse(status=404)
    item = get_object_or_404(model, pk=pk, household=request.household)
    occurrence = requested_occurrence(request, item) if kind == 'activity' and item.recurrence else None
    day = getattr(occurrence, 'instance_date', None)
    if request.method == 'POST':
        scope = chosen_scope(request) if day else 'all'
        if scope == 'following' and day == item.start_date:
            scope = 'all'
        message = 'Family member updated.' if kind == 'member' else 'Plan deleted. Preparation tasks remain in your task list.' if kind == 'activity' else 'Task deleted.'
        with transaction.atomic():
            household = Household.objects.select_for_update().get(pk=request.household.pk)
            item = model.objects.select_for_update().get(pk=pk, household=household)
            if not version_matches(request, item) or day and occurrence_of(item, day) is None:
                return conflict(request)
            if kind == 'member':
                item.archived = not item.archived
                item.version += 1
                item.save(update_fields=['archived', 'version'])
            elif scope == 'one':
                item.recurrence_exdates = item.recurrence_exdates + [day.isoformat()]
                item.version += 1
                item.save(update_fields=['recurrence_exdates', 'version'])
                message = 'This occurrence was deleted.'
            elif scope == 'following':
                item.recurrence = end_before(item.recurrence, item.start_date, day)
                item.overrides.filter(occurrence_date__gte=day).delete()
                item.version += 1
                item.save(update_fields=['recurrence', 'version'])
                message = 'This and following occurrences were deleted.'
            else:
                if kind == 'task' and item.recurrence and request.POST.get('task_scope') == 'skip':
                    following = next_task(item)
                    message = f'Skipped. Next due {following.due_date:%b} {following.due_date.day}.' if following else 'Task deleted. The repeat has ended.'
                elif kind == 'task' and item.recurrence:
                    message = 'Task deleted. It will not repeat again.'
                item.delete()
            bump(household)
        messages.success(request, message)
        return redirect('family' if kind == 'member' else 'tasks' if kind == 'task' else 'home')
    repeats = describe(item.recurrence, item.recurrence_start or item.due_date) if kind == 'task' else describe(item.recurrence, item.start_date) if kind == 'activity' else ''
    return render(request, 'planner/remove.html', {'item': item, 'kind': kind, 'occurrence': day, 'scopes': SCOPES, 'repeats': repeats})

@parent_only
@require_POST
def complete(request, pk):
    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=request.household.pk)
        task = get_object_or_404(Task.objects.select_for_update(), pk=pk, household=household)
        if not version_matches(request, task):
            return conflict(request)
        task.completed_at = None if task.completed_at else timezone.now()
        task.version += 1
        task.save(update_fields=['completed_at', 'version'])
        following = next_task(task) if task.completed_at else None
        bump(household)
    message = 'Task reopened.' if not task.completed_at else 'Task completed.'
    if following:
        message += f' Next due {following.due_date:%b} {following.due_date.day}.'
    messages.success(request, message)
    return redirect('tasks' if request.POST.get('origin') == 'tasks' else 'home')

@parent_only
@require_http_methods(['GET', 'POST'])
def lunches(request):
    day = chosen_date(request)
    first = day.replace(day=1)
    month_days = [first + timedelta(days=i) for i in range(calendar.monthrange(day.year, day.month)[1])]
    days = [d for d in month_days if d.weekday() < 5]
    if request.method == 'POST':
        try:
            chosen = sorted(set(date.fromisoformat(d) for d in request.POST.getlist('dates')))
        except ValueError:
            return HttpResponse('Choose valid school dates.', status=400)
        if request.POST.get('all_month'):
            chosen = days
        if not chosen or len(chosen) > 31 or any(d.weekday() > 4 for d in chosen):
            return HttpResponse('Select between 1 and 31 school days.', status=400)
        if any(d not in days for d in chosen):
            return HttpResponse('Select dates within the displayed month.', status=400)
        choice = request.POST.get('choice')
        if choice not in dict(LunchPlan._meta.get_field('choice').choices):
            return HttpResponse('Choose a lunch option.', status=400)
        child = get_object_or_404(FamilyMember, pk=request.POST.get('child'), household=request.household, archived=False, role='child')
        with transaction.atomic():
            household = Household.objects.select_for_update().get(pk=request.household.pk)
            if not version_matches(request, household):
                return conflict(request)
            old = []
            for day in chosen:
                existing = LunchPlan.objects.filter(household=household, child=child, date=day).first()
                old.append({'date': day.isoformat(), 'choice': existing.choice if existing else 'undecided'})
                LunchPlan.objects.update_or_create(household=household, child=child, date=day, defaults={'choice': choice})
            bump(household)
            request.session['lunch_undo'] = {'household': str(household.pk), 'child': str(child.pk), 'version': household.version, 'old': old, 'month': first.isoformat()}
        messages.success(request, f'Lunch updated for {child.name}. You can undo this change below.')
        return redirect(reverse('lunches') + '?date=' + first.isoformat())
    return render(request, 'planner/lunches.html', {'section': 'lunches', 'rows': lunch_rows(request.household, days), 'days': days, 'day': first, 'previous': (first - timedelta(days=1)).replace(day=1), 'next': (first + timedelta(days=32)).replace(day=1), 'version': request.household.version, 'choices': LunchPlan._meta.get_field('choice').choices, 'undo': request.session.get('lunch_undo')})

@parent_only
@require_POST
def undo_lunch(request):
    undo = request.session.get('lunch_undo')
    if not undo or undo['household'] != str(request.household.pk):
        return HttpResponse('No lunch change to undo.', status=400)
    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=request.household.pk)
        if household.version != undo['version']:
            return conflict(request)
        child = get_object_or_404(FamilyMember, pk=undo['child'], household=household)
        for old in undo['old']:
            LunchPlan.objects.update_or_create(household=household, child=child, date=old['date'], defaults={'choice': old['choice']})
        bump(household)
    request.session.pop('lunch_undo', None)
    messages.success(request, 'Lunch change undone.')
    return redirect(reverse('lunches') + '?date=' + undo.get('month', chosen_date(request).replace(day=1).isoformat()))

@parent_only
@require_GET
def settings(request):
    return render(request, 'planner/settings.html', {'section': 'settings', 'household': request.household})
