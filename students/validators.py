import os
from django.core.exceptions import ValidationError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


def validate_resume(file):
    # Skip files already saved; only check new uploads
    if getattr(file, '_committed', False):
        return
    if os.path.splitext(file.name)[1].lower() != '.pdf':
        raise ValidationError('Resume must be a PDF file.')
    if file.size > MAX_UPLOAD_BYTES:
        raise ValidationError('Resume must be smaller than 2 MB.')


def validate_image_size(file):
    if getattr(file, '_committed', False):
        return
    if file.size > MAX_UPLOAD_BYTES:
        raise ValidationError('Image must be smaller than 2 MB.')