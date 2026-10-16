from django import forms
from .models import FamilyMember
from .planner_forms import REPEAT_NAMES, add_repeat_fields

REMINDERS = [('', 'No reminder preference'), ('30', '30 minutes before'), ('60', '1 hour before'), ('1440', '1 day before'), ('2880', '2 days before')]

MAX_PHOTO = 8 * 1024 * 1024
PHOTO_TYPES = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG\r\n\x1a\n': 'image/png'}
FLYER_ATTRS = {'accept': 'image/jpeg,image/png,image/webp,image/*', 'capture': 'environment', 'data-flyer': ''}

def photo_type(data):
    """The image type from the file's first bytes (not its name), or None if unsupported."""
    for magic, kind in PHOTO_TYPES.items():
        if data.startswith(magic):
            return kind
    return 'image/webp' if data[:4] == b'RIFF' and data[8:12] == b'WEBP' else None

class PromptForm(forms.Form):
    prompt = forms.CharField(max_length=3000, required=False, label='What would you like to organize?', widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Logan has a birthday party Saturday at 2 PM. We need a gift.'}))
    photo = forms.FileField(required=False, label='Or snap a flyer (optional)', widget=forms.ClearableFileInput(attrs=FLYER_ATTRS))
    request_key = forms.UUIDField(widget=forms.HiddenInput)

    def clean_photo(self):
        """Return the photo as a data URL for OpenAI. It is never saved by the app (AI-10)."""
        upload = self.cleaned_data.get('photo')
        if not upload:
            return None
        if upload.size > MAX_PHOTO:
            raise forms.ValidationError('That photo is too large. Try again, or crop it to the flyer.')
        data = upload.read()
        kind = photo_type(data)
        if kind is None:
            raise forms.ValidationError('Use a JPEG, PNG or WebP photo. (On iPhone, Most Compatible camera format.)')
        import base64
        return f'data:{kind};base64,' + base64.b64encode(data).decode()

    def clean(self):
        data = super().clean()
        if not data.get('prompt', '').strip() and not data.get('photo') and not self.errors:
            raise forms.ValidationError('Describe what to organize, or add a photo of a flyer.')
        return data

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
    reminder_minutes = forms.TypedChoiceField(choices=REMINDERS, required=False, coerce=int, empty_value=None, label='Phone reminder')

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
    reminder_minutes = forms.TypedChoiceField(choices=REMINDERS, required=False, coerce=int, empty_value=None, label='Phone reminder')
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
