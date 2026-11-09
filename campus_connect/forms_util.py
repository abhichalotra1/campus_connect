from django.contrib import messages
from django.db import models


def flash_form_errors(request, *forms):
    """Show every error of the given forms as a message, labelled with its field."""
    for form in forms:
        for field, errors in form.errors.items():
            bound = form.fields.get(field)
            label = '' if field == '__all__' or bound is None else (bound.label or field.replace('_', ' ').capitalize())
            for error in errors:
                messages.error(request, f'{label}: {error}' if label else error)

def discard_unsaved_files(instance):
    """Put back the saved files after a rejected upload.

    Otherwise the re-rendered form would show the rejected file as the "current" one,
    with a link to something that was never stored.
    """
    saved = type(instance).objects.filter(pk=instance.pk).first()
    for field in instance._meta.get_fields():
        if isinstance(field, models.FileField):
            current = getattr(instance, field.name)
            if current and not current._committed:
                setattr(instance, field.name, getattr(saved, field.name) if saved else None)

