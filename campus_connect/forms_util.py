from django.contrib import messages


def flash_form_errors(request, *forms):
    """Show every error of the given forms as a message, labelled with its field."""
    for form in forms:
        for field, errors in form.errors.items():
            bound = form.fields.get(field)
            label = '' if field == '__all__' or bound is None else (bound.label or field.replace('_', ' ').capitalize())
            for error in errors:
                messages.error(request, f'{label}: {error}' if label else error)
