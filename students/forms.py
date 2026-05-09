from django import forms
from .models import StudentProfile
from accounts.models import User


class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = [
            'profile_pic', 'branch', 'cgpa', 'roll_number',
            'passing_year', 'skills', 'certifications',
            'about', 'resume', 'linkedin', 'github',
        ]
        widgets = {
            'branch':       forms.Select(attrs={'class': 'form-select'}),
            'cgpa':         forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '10'}),
            'roll_number':  forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 21CSE001'}),
            'passing_year': forms.NumberInput(attrs={'class': 'form-control', 'min': '2020', 'max': '2030'}),
            'skills':       forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Python, Django, React, ...'}),
            'certifications': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'AWS Certified, Google ML, ...'}),
            'about':        forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Tell us about yourself...'}),
            'linkedin':     forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://linkedin.com/in/...'}),
            'github':       forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://github.com/...'}),
            'resume':       forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.doc,.docx'}),
            'profile_pic':  forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }


class UserBasicForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
        }


class RecruiterProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
        }