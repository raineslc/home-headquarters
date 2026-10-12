from django import forms
from django.contrib.auth.forms import AuthenticationForm

class SignInForm(AuthenticationForm):
    username = forms.EmailField(label='Email', widget=forms.EmailInput(attrs={'autocomplete': 'username'}))
    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()

class SetupForm(forms.Form):
    token = forms.CharField(label='Private setup code', widget=forms.PasswordInput(attrs={'autocomplete': 'off'}), max_length=128)
    email = forms.EmailField(max_length=254)
    name = forms.CharField(label='Your name', max_length=100)
    household = forms.CharField(label='Household name', max_length=100, initial='Home Headquarters')
    password = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password_confirm = forms.CharField(label='Confirm password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

class RecordForm(forms.Form):
    title = forms.CharField(label='Note', max_length=200, widget=forms.TextInput(attrs={'placeholder': 'A note to verify shared storage'}))

class RestoreForm(forms.Form):
    backup = forms.FileField(label='Household export (.json)')
