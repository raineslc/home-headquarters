"""Reusable list templates and checklists on activities and tasks (LIST-01).

A template ("Swim bag: towel, goggles, snack") is copied onto an activity or task as checklist
items. On a repeating activity the items are shared by the series and ticks are kept per
occurrence date; a repeating task's next task receives a fresh, unticked copy.
"""
from datetime import date
from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST
from .models import Activity, ChecklistItem, Household, ListTemplate, Task
from .views import parent_only

MAX_ITEMS = 50

class TemplateForm(forms.Form):
    name = forms.CharField(max_length=100, label='List name')
    items = forms.CharField(widget=forms.Textarea(attrs={'rows': 8}), label='Items (one per line)')

    def clean_items(self):
        lines = [' '.join(line.split()) for line in self.cleaned_data['items'].splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            raise forms.ValidationError('Add at least one item.')
        if len(lines) > MAX_ITEMS:
            raise forms.ValidationError(f'A list can have up to {MAX_ITEMS} items.')
        if any(len(line) > 200 for line in lines):
            raise forms.ValidationError('Each item can be up to 200 characters.')
        return lines

def checklist_rows(owner, occurrence=None):
    """Checklist items of an activity or task with their ticked state (per occurrence for a series)."""
    rows = []
    for item in owner.checklist_items.all():
        done = occurrence.isoformat() in item.done_dates if occurrence else item.done_at is not None
        rows.append({'item': item, 'done': done})
    return rows

def copy_checklist(source_task, new_task):
    """Give the next task in a repeating series a fresh, unticked copy of the checklist."""
    ChecklistItem.objects.bulk_create([ChecklistItem(household_id=new_task.household_id, task=new_task, text=item.text, position=item.position)
                                       for item in source_task.checklist_items.all()])

def owner_for(request, kind, pk):
    model = {'activity': Activity, 'task': Task}.get(kind)
    if model is None:
        raise Http404
    return get_object_or_404(model, pk=pk, household=request.household)

def safe_next(request, fallback):
    target = request.POST.get('next', '')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback

@parent_only
@require_POST
def checklist_action(request, kind, pk):
    owner = owner_for(request, kind, pk)
    fallback = f'/activity/{owner.pk}/' if kind == 'activity' else f'/plan/task/{owner.pk}/edit/'
    action = request.POST.get('action', '')
    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=request.household.pk)
        items = ChecklistItem.objects.filter(household=household, **{kind: owner})
        next_position = (max(items.values_list('position', flat=True), default=-1)) + 1
        if action == 'add':
            text = ' '.join(request.POST.get('text', '').split())[:200]
            if not text:
                messages.error(request, 'Type an item to add.')
            elif items.count() >= MAX_ITEMS:
                messages.error(request, f'A checklist can have up to {MAX_ITEMS} items.')
            else:
                ChecklistItem.objects.create(household=household, text=text, position=next_position, **{kind: owner})
        elif action == 'template':
            template = ListTemplate.objects.filter(household=household, pk=request.POST.get('template') or None).first()
            if template is None:
                messages.error(request, 'Choose a list to add.')
            else:
                existing = {item.text.lower() for item in items}
                new = [text for text in template.items if text.lower() not in existing][:max(0, MAX_ITEMS - items.count())]
                ChecklistItem.objects.bulk_create([ChecklistItem(household=household, text=text, position=next_position + i, **{kind: owner})
                                                   for i, text in enumerate(new)])
                messages.success(request, f'Added “{template.name}” ({len(new)} item{"s" if len(new) != 1 else ""}).')
        elif action in ('done', 'undone', 'remove'):
            item = items.filter(pk=request.POST.get('item') or None).first()
            if item is None:
                return HttpResponse('That item is no longer on this checklist.', status=409)
            if action == 'remove':
                item.delete()
            else:
                occurrence = request.POST.get('occurrence')
                if occurrence:
                    try:
                        day = date.fromisoformat(occurrence).isoformat()
                    except ValueError:
                        return HttpResponse('Unknown occurrence.', status=400)
                    dates = set(item.done_dates)
                    dates.add(day) if action == 'done' else dates.discard(day)
                    item.done_dates = sorted(dates)
                else:
                    item.done_at = timezone.now() if action == 'done' else None
                item.save(update_fields=['done_dates', 'done_at'])
        else:
            return HttpResponse('Choose a checklist action.', status=400)
    return redirect(safe_next(request, fallback))

@parent_only
@require_http_methods(['GET', 'POST'])
def lists(request):
    form = TemplateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ListTemplate.objects.create(household=request.household, name=form.cleaned_data['name'], items=form.cleaned_data['items'])
        messages.success(request, 'List saved. Add it to an activity or task from its page.')
        return redirect('lists')
    return render(request, 'lists/index.html', {'section': 'settings', 'form': form,
                                                'templates': ListTemplate.objects.filter(household=request.household)})

@parent_only
@require_http_methods(['GET', 'POST'])
def list_edit(request, pk):
    template = get_object_or_404(ListTemplate, pk=pk, household=request.household)
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        template.delete()
        messages.success(request, 'List deleted. Checklists already added to plans are unchanged.')
        return redirect('lists')
    form = TemplateForm(request.POST or None, initial={'name': template.name, 'items': '\n'.join(template.items)})
    if request.method == 'POST' and form.is_valid():
        template.name, template.items = form.cleaned_data['name'], form.cleaned_data['items']
        template.save(update_fields=['name', 'items'])
        messages.success(request, 'List updated. Checklists already added to plans are unchanged.')
        return redirect('lists')
    return render(request, 'lists/edit.html', {'section': 'settings', 'form': form, 'template': template})
