from django import forms
from .models import FamilyMember
from .planner_forms import REPEAT_NAMES, add_repeat_fields

REMINDERS = [('', 'No reminder preference'), ('30', '30 minutes before'), ('60', '1 hour before'), ('1440', '1 day before'), ('2880', '2 days before')]

class PromptForm(forms.Form):
    prompt = forms.CharField(max_length=3000, label='What would you like to organize?', widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Logan has a birthday party Saturday at 2 PM. We need a gift.'}))
    request_key = forms.UUIDField(widget=forms.HiddenInput)

class ClarifyForm(forms.Form):
    answer = forms.CharField(max_length=2000, label='Add the missing details or describe a change', widget=forms.Textarea(attrs={'rows': 3}))
    version = forms.IntegerField(widget=forms.HiddenInput)

class EventDraftForm(forms.Form):
    title = forms.CharField(max_length=200)
    start_date = forms.DateField(required=False, label='Date', widget=forms.DateInput(attrs={'type': 'date'}))
    start_time = forms.TimeField(required=False, label='Start', widget=forms.TimeInput(attrs={'type': 'time'}))
    end_date = forms.DateField(required=False, label='Last day', widget=forms.DateInput(attrs={'type': 'date'}))
    end_time = forms.TimeField(required=False, label='End', widget=forms.TimeInput(attrs={'type': 'time'}))
    all_day = forms.BooleanField(required=False)
    participants = forms.ModelMultipleChoiceField(queryset=FamilyMember.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    location = forms.CharField(max_length=300, required=False)
    notes = forms.CharField(max_length=5000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    reminder_minutes = forms.TypedChoiceField(choices=REMINDERS, required=False, coerce=int, empty_value=None, label='Reminder preference (delivery not enabled)')

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['participants'].queryset = FamilyMember.objects.filter(household=household, archived=False).order_by('name')
        add_repeat_fields(self, '')

class TaskDraftForm(forms.Form):
    title = forms.CharField(max_length=200)
    assignee = forms.ModelChoiceField(queryset=FamilyMember.objects.none(), required=False, empty_label='Household')
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    due_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'type': 'time'}))
    high_priority = forms.BooleanField(required=False)
    notes = forms.CharField(max_length=5000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    reminder_minutes = forms.TypedChoiceField(choices=REMINDERS, required=False, coerce=int, empty_value=None, label='Reminder preference (delivery not enabled)')
    search_prompt = forms.CharField(max_length=500, required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Optional external search prompt')
    search_questions = forms.CharField(max_length=500, required=False, label='Details to check before searching')

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = FamilyMember.objects.filter(household=household, archived=False).order_by('name')
        add_repeat_fields(self, '')

def json_payload(data):
    result = dict(data)
    for key in ('start_date', 'end_date', 'start_time', 'end_time', 'due_date', 'due_time', 'until'):
        if key in result:
            result[key] = result[key].isoformat() if result[key] else None
    if 'participants' in result:
        result['participants'] = [str(member.pk) for member in result['participants']]
    if 'assignee' in result:
        result['assignee'] = str(result['assignee'].pk) if result['assignee'] else None
    return result
