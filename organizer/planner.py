import calendar
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .models import Activity, FamilyMember, Household, LunchPlan, Task
from .planner_forms import ActivityForm, MemberForm, TaskForm
from .views import parent_only

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

@parent_only
@require_GET
def dashboard(request):
    day = chosen_date(request)
    today = timezone.localdate(timezone=ZoneInfo(request.household.timezone))
    mode = request.GET.get('view', 'week')
    if mode not in ('week', 'month', 'agenda'):
        mode = 'week'
    monday = day - timedelta(days=day.weekday())
    first = day.replace(day=1) if mode == 'month' else monday
    start = first - timedelta(days=first.weekday()) if mode == 'month' else first
    count = 42 if mode == 'month' else 7
    days = [start + timedelta(days=i) for i in range(count)]
    end = days[-1]
    events = list(Activity.objects.filter(household=request.household, start_date__lte=end, end_date__gte=start).prefetch_related('participants'))
    task_query = Task.objects.filter(household=request.household).select_related('assignee', 'activity')
    due_tasks = list(task_query.filter(completed_at__isnull=True, due_date__range=(start, end)))
    school_lunches = list(LunchPlan.objects.filter(household=request.household, date__range=(start, end), choice='school', child__household=request.household, child__role='child', child__archived=False).select_related('child').order_by('child__name'))
    cells = [{'date': d, 'today': d == today, 'in_month': d.month == day.month, 'events': [e for e in events if e.start_date <= d <= e.end_date], 'tasks': [t for t in due_tasks if t.due_date == d], 'school_lunches': [lunch for lunch in school_lunches if lunch.date == d]} for d in days]
    priorities = task_query.filter(completed_at__isnull=True).filter(Q(due_date__lte=monday + timedelta(days=6)) | Q(due_date__isnull=True)).order_by('due_date', 'title')[:8]
    today_events = Activity.objects.filter(household=request.household, start_date__lte=today, end_date__gte=today).prefetch_related('participants')
    if mode == 'month':
        previous = (first - timedelta(days=1)).replace(day=1)
        next_day = (first + timedelta(days=32)).replace(day=1)
    else:
        previous, next_day = day - timedelta(days=7), day + timedelta(days=7)
    return render(request, 'planner/dashboard.html', {'section': 'home', 'day': day, 'today': today, 'mode': mode, 'cells': cells, 'previous': previous, 'next': next_day, 'week_start': monday, 'week_end': monday + timedelta(days=6), 'priorities': priorities, 'today_events': today_events, 'today_tasks': task_query.filter(completed_at__isnull=True, due_date=today), 'packed': LunchPlan.objects.filter(household=request.household, date=today, choice='pack', child__archived=False).select_related('child')})

@parent_only
@require_GET
def family(request):
    return render(request, 'planner/family.html', {'section': 'family', 'members': FamilyMember.objects.filter(household=request.household).order_by('archived', 'role', 'name')})

@parent_only
@require_GET
def tasks(request):
    status = request.GET.get('status', 'open')
    query = Task.objects.filter(household=request.household).select_related('assignee', 'activity')
    if status != 'all':
        query = query.filter(completed_at__isnull=status != 'done')
    return render(request, 'planner/tasks.html', {'section': 'tasks', 'tasks': query, 'status': status, 'today': timezone.localdate(timezone=ZoneInfo(request.household.timezone))})

@parent_only
@require_GET
def activity_detail(request, pk):
    item = get_object_or_404(Activity.objects.prefetch_related('participants'), pk=pk, household=request.household)
    return render(request, 'planner/activity.html', {'section': 'home', 'item': item, 'tasks': item.tasks.select_related('assignee').all()})

@parent_only
@require_http_methods(['GET', 'POST'])
def edit(request, kind, pk=None):
    config = {'activity': (Activity, ActivityForm, 'activity'), 'task': (Task, TaskForm, 'task'), 'member': (FamilyMember, MemberForm, 'family member')}
    if kind not in config:
        return HttpResponse(status=404)
    model, form_class, label = config[kind]
    instance = get_object_or_404(model, pk=pk, household=request.household) if pk else None
    initial = {}
    if not pk and kind == 'activity':
        initial = {'start_date': chosen_date(request), 'end_date': chosen_date(request)}
    if not pk and kind == 'task' and request.GET.get('activity'):
        linked = get_object_or_404(Activity, pk=request.GET['activity'], household=request.household)
        initial['activity'] = linked.pk
    form = form_class(request.POST or None, instance=instance, household=request.household, initial=initial)
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

@parent_only
@require_http_methods(['GET', 'POST'])
def remove(request, kind, pk):
    model = {'activity': Activity, 'task': Task, 'member': FamilyMember}.get(kind)
    if not model:
        return HttpResponse(status=404)
    item = get_object_or_404(model, pk=pk, household=request.household)
    if request.method == 'POST':
        with transaction.atomic():
            household = Household.objects.select_for_update().get(pk=request.household.pk)
            item = model.objects.select_for_update().get(pk=pk, household=household)
            if not version_matches(request, item):
                return conflict(request)
            if kind == 'member':
                item.archived = not item.archived
                item.version += 1
                item.save(update_fields=['archived', 'version'])
            else:
                item.delete()
            bump(household)
        messages.success(request, 'Family member updated.' if kind == 'member' else 'Plan deleted. Preparation tasks remain in your task list.' if kind == 'activity' else 'Task deleted.')
        return redirect('family' if kind == 'member' else 'tasks' if kind == 'task' else 'home')
    return render(request, 'planner/remove.html', {'item': item, 'kind': kind})

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
        bump(household)
    messages.success(request, 'Task reopened.' if not task.completed_at else 'Task completed.')
    return redirect('tasks' if request.POST.get('origin') == 'tasks' else 'home')

@parent_only
@require_http_methods(['GET', 'POST'])
def lunches(request):
    day = chosen_date(request)
    monday = day - timedelta(days=day.weekday())
    days = [monday + timedelta(days=i) for i in range(5)]
    if request.method == 'POST':
        try:
            chosen = sorted(set(date.fromisoformat(d) for d in request.POST.getlist('dates')))
        except ValueError:
            return HttpResponse('Choose valid school dates.', status=400)
        if not chosen or len(chosen) > 31 or any(d.weekday() > 4 for d in chosen):
            return HttpResponse('Select between 1 and 31 school days.', status=400)
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
            request.session['lunch_undo'] = {'household': str(household.pk), 'child': str(child.pk), 'version': household.version, 'old': old}
        messages.success(request, f'Lunch updated for {child.name}. You can undo this change below.')
        return redirect(reverse('lunches') + '?date=' + monday.isoformat())
    return render(request, 'planner/lunches.html', {'section': 'lunches', 'rows': lunch_rows(request.household, days), 'days': days, 'day': monday, 'previous': monday - timedelta(days=7), 'next': monday + timedelta(days=7), 'version': request.household.version, 'choices': LunchPlan._meta.get_field('choice').choices, 'undo': request.session.get('lunch_undo')})

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
    return redirect('lunches')

@parent_only
@require_GET
def settings(request):
    return render(request, 'planner/settings.html', {'section': 'settings', 'household': request.household})

