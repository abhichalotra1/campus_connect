from django import forms

from .models import Achievement, Education, Experience, Project


class MonthInput(forms.DateInput):
    """A month picker (<input type="month">). The browser sends 2025-06; the form turns it into 1 Jun 2025."""
    input_type = 'month'

    def __init__(self, attrs=None):
        super().__init__(attrs, format='%Y-%m')


class MonthField(forms.DateField):
    widget = MonthInput

    def __init__(self, **kwargs):
        kwargs.setdefault('input_formats', ['%Y-%m', '%Y-%m-%d'])
        super().__init__(**kwargs)


class NormalizedText(forms.CharField):
    """Count a line break as one character, like the browser's maxlength does."""

    def to_python(self, value):
        value = super().to_python(value)
        return value.replace('\r\n', '\n').replace('\r', '\n') if value else value


class _ResumeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                continue
            css = 'form-select' if isinstance(widget, forms.Select) else 'form-control'
            widget.attrs.setdefault('class', css)
            widget.attrs.setdefault('autocomplete', 'off')


class EducationForm(_ResumeForm):
    class Meta:
        model = Education
        fields = ['institution', 'degree', 'field_of_study', 'start_year', 'end_year', 'grade']
        labels = {'institution': 'College or school', 'degree': 'Degree', 'field_of_study': 'Branch or subject',
                  'start_year': 'Start year', 'end_year': 'End year (or expected)', 'grade': 'Grade'}
        widgets = {
            'institution': forms.TextInput(attrs={'placeholder': 'e.g., Punjab Engineering College'}),
            'degree': forms.TextInput(attrs={'placeholder': 'e.g., B.Tech'}),
            'field_of_study': forms.TextInput(attrs={'placeholder': 'e.g., Computer Science'}),
            'start_year': forms.NumberInput(attrs={'placeholder': '2023', 'min': 1990, 'max': 2050}),
            'end_year': forms.NumberInput(attrs={'placeholder': '2027', 'min': 1990, 'max': 2050}),
            'grade': forms.TextInput(attrs={'placeholder': 'e.g., 8.4 CGPA'}),
        }


class ExperienceForm(_ResumeForm):
    start_date = MonthField(label='Start month')
    end_date = MonthField(label='End month', required=False)
    description = NormalizedText(
        label='What you did', required=False, max_length=900,
        widget=forms.Textarea(attrs={'rows': 4, 'maxlength': 900,
                                     'placeholder': 'One point per line. Start with a verb and add a number if you can.'}),
        help_text='One bullet point per line. Up to 6 are shown.')

    class Meta:
        model = Experience
        fields = ['role', 'company', 'start_date', 'end_date', 'is_current', 'description']
        labels = {'role': 'Role', 'company': 'Company or organisation'}
        widgets = {
            'role': forms.TextInput(attrs={'placeholder': 'e.g., Software Intern'}),
            'company': forms.TextInput(attrs={'placeholder': 'e.g., Infosys'}),
        }


class ProjectForm(_ResumeForm):
    description = NormalizedText(
        label='What it does', required=False, max_length=900,
        widget=forms.Textarea(attrs={'rows': 4, 'maxlength': 900,
                                     'placeholder': 'One point per line: what you built and what it achieved.'}),
        help_text='One bullet point per line. Up to 6 are shown.')

    class Meta:
        model = Project
        fields = ['title', 'tech', 'link', 'description']
        labels = {'title': 'Project name', 'tech': 'Tech used', 'link': 'Link (GitHub or live site)'}
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'e.g., Campus Connect'}),
            'tech': forms.TextInput(attrs={'placeholder': 'e.g., Django, PostgreSQL, Bootstrap'}),
            'link': forms.URLInput(attrs={'placeholder': 'https://github.com/you/project'}),
        }


class AchievementForm(_ResumeForm):
    class Meta:
        model = Achievement
        fields = ['text']
        labels = {'text': 'Achievement'}
        widgets = {'text': forms.TextInput(attrs={'maxlength': 200,
                                                  'placeholder': 'e.g., Winner, Smart India Hackathon 2025 (college round)'})}
