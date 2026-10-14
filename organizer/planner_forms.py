import uuid
from datetime import datetime, timezone as utc_timezone
from zoneinfo import ZoneInfo
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import Activity, FamilyMember, Task
from .recurrence import WEEKDAYS, WEEKDAY_NAMES, build_rule, first_on_or_after, rule_fields

def has_family_calendar(household):
    from .models import FamilyCalendar
    return FamilyCalendar.objects.filter(household=household).exists()

REPEATS = [('', 'Does not repeat'), ('DAILY', 'Daily'), ('WEEKLY', 'Weekly'), ('MONTHLY', 'Monthly'), ('YEARLY', 'Yearly')]

REPEAT_NAMES = ['repeat', 'interval', 'weekdays', 'monthly_by', 'ends', 'until', 'count']

def add_repeat_fields(form, rule):
    """Structured repeat controls; the form builds and validates an RRULE from them."""
    form.repeat_names = REPEAT_NAMES
    initial = rule_fields(rule)
    form.fields['repeat'] = forms.ChoiceField(choices=REPEATS, required=False, initial=initial['repeat'], label='Repeats')
    form.fields['interval'] = forms.IntegerField(min_value=1, max_value=99, initial=initial['interval'], required=False, label='Every (days, weeks, months or years)')
    form.fields['weekdays'] = forms.MultipleChoiceField(choices=list(zip(WEEKDAYS, WEEKDAY_NAMES)), required=False, initial=initial.get('weekdays', []),
                                                        widget=forms.CheckboxSelectMultiple, label='On (weekly)')
    form.fields['monthly_by'] = forms.ChoiceField(choices=[('day', 'Same day of the month'), ('weekday', 'Same weekday, such as the second Tuesday')],
                                                  initial=initial.get('monthly_by', 'day'), required=False, label='Monthly on')
    form.fields['ends'] = forms.ChoiceField(choices=[('never', 'Never'), ('until', 'On a date'), ('count', 'After a number of times')],
                                            initial=initial['ends'], required=False, label='Ends')
    form.fields['until'] = forms.DateField(required=False, initial=initial.get('until'), widget=forms.DateInput(attrs={'type': 'date'}), label='End date')
    form.fields['count'] = forms.IntegerField(min_value=1, max_value=500, required=False, initial=initial.get('count'), label='Number of times')

def clean_repeat(form, data, anchor, anchor_field, realign=''):
    """Build the rule. realign='forward' moves a non-matching first date to the next match (and the
    end date with it); 'skip' leaves alignment to the caller; '' requires the first date to match."""
    if not data.get('repeat'):
        return ''
    if not anchor:
        form.add_error(anchor_field, 'Choose a date for the first occurrence.')
        return ''
    ends = data.get('ends') or 'never'
    if ends == 'until' and not data.get('until'):
        form.add_error('until', 'Choose the last date.')
        return ''
    if ends == 'count' and not data.get('count'):
        form.add_error('count', 'Choose how many times.')
        return ''
    try:
        rule = build_rule(data['repeat'], data.get('interval') or 1, anchor, data.get('weekdays') or (),
                          data.get('monthly_by') or 'day', ends, data.get('until'), data.get('count'), check_anchor=not realign)
        if realign == 'forward':
            first = first_on_or_after(rule, anchor)
            if first is None:
                raise ValidationError('This repeat pattern has no dates on or after the chosen date.')
            if first != anchor:
                data['end_date'] = data['end_date'] + (first - anchor) if data.get('end_date') else first
                data[anchor_field] = first
        return rule
    except ValidationError as error:
        form.add_error('repeat', error)
        return ''

class VersionForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput, initial=0, min_value=0)
    repeat_names = ()

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        if self.instance.pk and not self.instance._state.adding:
            self.fields['version'].initial = self.instance.version

class MemberForm(VersionForm):
    class Meta:
        model = FamilyMember
        fields = ['name', 'role', 'color']

class ActivityForm(VersionForm):
    class Meta:
        model = Activity
        fields = ['title', 'start_date', 'start_time', 'end_date', 'end_time', 'all_day', 'participants', 'location', 'notes', 'reminder_minutes', 'google_sync']
        widgets = {'start_date': forms.DateInput(attrs={'type': 'date'}), 'end_date': forms.DateInput(attrs={'type': 'date'}), 'start_time': forms.TimeInput(attrs={'type': 'time'}), 'end_time': forms.TimeInput(attrs={'type': 'time'}), 'participants': forms.CheckboxSelectMultiple(), 'notes': forms.Textarea(attrs={'rows': 3})}
        labels = {'end_date': 'Last day', 'participants': 'Who is going?', 'google_sync': 'Also add to the family Google calendar'}

    def __init__(self, *args, household, repeat=False, realign='', **kwargs):
        super().__init__(*args, household=household, **kwargs)
        self.repeat, self.realign = repeat, realign
        if repeat:
            add_repeat_fields(self, self.instance.recurrence)
        included = self.instance.participants.values_list('pk', flat=True) if not self.instance._state.adding else []
        if 'participants' in self.fields:
            self.fields['participants'].queryset = FamilyMember.objects.filter(household=household).filter(Q(archived=False) | Q(pk__in=included)).order_by('name')
        if 'reminder_minutes' in self.fields:
            from .assistant_forms import REMINDERS
            self.fields['reminder_minutes'] = forms.TypedChoiceField(choices=REMINDERS, coerce=int, empty_value=None, required=False, label='Reminder preference (delivery not enabled)')
        if 'google_sync' in self.fields:
            if not has_family_calendar(household) and not self.instance.google_sync:
                del self.fields['google_sync']  # nothing to choose until the family Google calendar exists
            elif self.instance._state.adding:
                self.fields['google_sync'].initial = True

    def clean(self):
        data = super().clean()
        start, end = data.get('start_date'), data.get('end_date')
        if data.get('all_day'):
            data['start_time'] = data['end_time'] = None
        else:
            for field in ('start_time', 'end_time'):
                if not data.get(field):
                    self.add_error(field, 'Choose a time, or mark this as all day.')
            if start and end and data.get('start_time') and data.get('end_time'):
                zone = ZoneInfo(self.household.timezone)
                moments = []
                for day, field in [(start, 'start_time'), (end, 'end_time')]:
                    naive = datetime.combine(day, data[field])
                    aware = naive.replace(tzinfo=zone)
                    if aware.astimezone(utc_timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
                        self.add_error(field, 'This time does not exist because the clocks change. Choose another time.')
                    if aware.utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset():
                        self.add_error(field, 'This time falls within a clock change. Choose an unambiguous time for this preview.')
                    moments.append(aware)
                if moments[1] <= moments[0]:
                    self.add_error('end_time', 'The end must be after the start.')
        if start and end and end < start:
            self.add_error('end_date', 'The last day cannot be before the first day.')
        if self.repeat:
            data['recurrence'] = clean_repeat(self, data, start, 'start_date', self.realign)
        return data

    def save(self, commit=True):
        if self.repeat:
            self.instance.recurrence = self.cleaned_data['recurrence']
        return super().save(commit)

class TaskForm(VersionForm):
    class Meta:
        model = Task
        fields = ['title', 'high_priority', 'assignee', 'due_date', 'due_time', 'activity', 'notes', 'reminder_minutes', 'search_prompt', 'search_questions']
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'}), 'due_time': forms.TimeInput(attrs={'type': 'time'}), 'notes': forms.Textarea(attrs={'rows': 3})}
        labels = {'activity': 'Preparation for activity', 'assignee': 'Responsible person'}

    def __init__(self, *args, household, repeat=False, **kwargs):
        super().__init__(*args, household=household, **kwargs)
        self.repeat = repeat
        if repeat:
            add_repeat_fields(self, self.instance.recurrence)
        self.fields['assignee'].queryset = FamilyMember.objects.filter(household=household).filter(Q(archived=False) | Q(pk=self.instance.assignee_id)).order_by('name')
        self.fields['assignee'].empty_label = 'Household'
        if 'activity' in self.fields:
            self.fields['activity'].queryset = Activity.objects.filter(household=household)
        if 'reminder_minutes' in self.fields:
            from .assistant_forms import REMINDERS
            self.fields['reminder_minutes'] = forms.TypedChoiceField(choices=REMINDERS, coerce=int, empty_value=None, required=False, label='Reminder preference (delivery not enabled)')
        if 'search_questions' in self.fields:
            self.fields['search_questions'].label = 'Details to check before searching'

    def clean(self):
        data = super().clean()
        if data.get('due_time') and not data.get('due_date'):
            self.add_error('due_date', 'Choose a date for this deadline.')
        if data.get('reminder_minutes') and not data.get('due_date'):
            self.add_error('due_date', 'Choose a deadline to save a reminder preference.')
        if self.repeat:
            data['recurrence'] = clean_repeat(self, data, data.get('due_date'), 'due_date')
        return data

    def save(self, commit=True):
        if self.repeat:
            rule = self.cleaned_data['recurrence']
            if rule and (rule != self.instance.recurrence or not self.instance.series_key):
                # A new or changed rule starts a new series from this task's due date.
                self.instance.recurrence_start = self.cleaned_data['due_date']
                self.instance.series_key = uuid.uuid4()
            elif not rule:
                self.instance.recurrence_start = self.instance.series_key = None
            self.instance.recurrence = rule
        return super().save(commit)

class QuickActivityForm(ActivityForm):
    class Meta(ActivityForm.Meta):
        fields = ['title', 'start_date', 'start_time', 'end_time', 'all_day']
        labels = {'start_date': 'Date'}

    def clean(self):
        self.cleaned_data['end_date'] = self.cleaned_data.get('start_date')
        return super().clean()

class QuickTaskForm(TaskForm):
    class Meta(TaskForm.Meta):
        fields = ['title', 'due_date', 'assignee', 'high_priority']

class BulkActivityForm(ActivityForm):
    """Details shared by every date in a multi-date add; each date is then checked with ActivityForm."""
    batch = forms.UUIDField(widget=forms.HiddenInput)

    class Meta(ActivityForm.Meta):
        fields = ['title', 'start_time', 'end_time', 'all_day', 'participants', 'location', 'notes', 'reminder_minutes', 'google_sync']

    def clean(self):
        data = super().clean()
        if not data.get('all_day') and data.get('start_time') and data.get('end_time') and data['end_time'] <= data['start_time']:
            self.add_error('end_time', 'The end must be after the start.')
        return data

