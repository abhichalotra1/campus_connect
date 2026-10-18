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


ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def validate_image(file):
    """Accept only real, small raster images (no SVG: it can carry scripts).

    Checks the extension, the size, and that Pillow can actually read the bytes, so a Word
    file renamed to .png is rejected here instead of failing later inside the storage service.
    """
    if getattr(file, '_committed', False):
        return  # already stored
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError('Image must be a JPG, PNG, GIF or WebP file.')
    if file.size > MAX_UPLOAD_BYTES:
        raise ValidationError('Image must be smaller than 2 MB.')

    from PIL import Image  # local import keeps module import light for migrations
    raw = getattr(file, 'file', file)
    try:
        raw.seek(0)
        with Image.open(raw) as img:
            img.verify()
    except Exception:
        raise ValidationError('This file is not a valid image.')
    finally:
        try:
            raw.seek(0)
        except Exception:
            pass

