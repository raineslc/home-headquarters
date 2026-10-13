from datetime import datetime, timezone as utc_timezone
from zoneinfo import ZoneInfo
from django import forms
from .models import Activity, FamilyMember, Task

class VersionForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput, initial=0, min_value=0)

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
        fields = ['title', 'start_date', 'start_time', 'end_date', 'end_time', 'all_day', 'participants', 'location', 'notes']
        widgets = {'start_date': forms.DateInput(attrs={'type': 'date'}), 'end_date': forms.DateInput(attrs={'type': 'date'}), 'start_time': forms.TimeInput(attrs={'type': 'time'}), 'end_time': forms.TimeInput(attrs={'type': 'time'}), 'participants': forms.CheckboxSelectMultiple(), 'notes': forms.Textarea(attrs={'rows': 3})}
        labels = {'end_date': 'Last day', 'participants': 'Who is going?'}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, household=household, **kwargs)
        self.fields['participants'].queryset = FamilyMember.objects.filter(household=household, archived=False).order_by('name')

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
        return data

class TaskForm(VersionForm):
    class Meta:
        model = Task
        fields = ['title', 'assignee', 'due_date', 'due_time', 'activity', 'notes']
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'}), 'due_time': forms.TimeInput(attrs={'type': 'time'}), 'notes': forms.Textarea(attrs={'rows': 3})}
        labels = {'activity': 'Preparation for activity', 'assignee': 'Responsible person'}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, household=household, **kwargs)
        self.fields['assignee'].queryset = FamilyMember.objects.filter(household=household, archived=False).order_by('name')
        self.fields['assignee'].empty_label = 'Household'
        self.fields['activity'].queryset = Activity.objects.filter(household=household)

    def clean(self):
        data = super().clean()
        if data.get('due_time') and not data.get('due_date'):
            self.add_error('due_date', 'Choose a date for this deadline.')
        return data
