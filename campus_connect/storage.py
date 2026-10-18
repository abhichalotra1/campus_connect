"""Cloudinary-backed media storage.

Render's disk is wiped on every deploy, so uploads must live off-box. This storage keeps
all FileField/ImageField uploads on Cloudinary and is switched on simply by setting the
CLOUDINARY_URL environment variable (see settings.STORAGES).

* Images (profile pictures, logos) are public Cloudinary image URLs.
* Resumes are stored as Cloudinary *raw* files and are never linked directly: `url()` returns
  a Django route (students.views.resume_download_view) that checks permissions first.
  Names are random UUIDs, so the underlying Cloudinary links cannot be guessed.

Stored names look like "resumes/<uuid>.pdf" / "profile_pics/<uuid>.jpg", exactly like the
local FileSystemStorage names, so no migration or data change is needed.
"""
import logging
import posixpath
import urllib.request
import uuid

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.urls import reverse
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)

# Upload folders whose files must not be linked directly
PRIVATE_PREFIXES = ('resumes/',)


@deconstructible
class CloudinaryMediaStorage(Storage):

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def is_private(name):
        return name.startswith(PRIVATE_PREFIXES)

    @staticmethod
    def _public_id_and_format(name):
        stem, ext = posixpath.splitext(name)
        return stem, ext.lstrip('.')

    # ── Storage API ──────────────────────────────────────────────────────
    def get_available_name(self, name, max_length=None):
        # Always a fresh random name: never collides, never guessable, ignores the user's filename.
        folder, filename = posixpath.split(name)
        ext = posixpath.splitext(filename)[1].lower()
        return posixpath.join(folder, f'{uuid.uuid4().hex}{ext}')

    def _save(self, name, content):
        if hasattr(content, 'seek'):
            content.seek(0)
        if self.is_private(name):
            # raw files keep their extension inside the public_id
            result = cloudinary.uploader.upload(
                content, public_id=name, resource_type='raw',
                overwrite=False, filename=posixpath.basename(name),
            )
            return result['public_id']
        public_id, _ = self._public_id_and_format(name)
        result = cloudinary.uploader.upload(
            content, public_id=public_id, resource_type='image',
            overwrite=False, filename=posixpath.basename(name),
        )
        return f"{result['public_id']}.{result['format']}"

    def exists(self, name):
        return False  # names are unique, so Django never needs to rename

    def url(self, name):
        if self.is_private(name):
            return reverse('resume_download', kwargs={'name': name})
        public_id, fmt = self._public_id_and_format(name)
        return cloudinary.utils.cloudinary_url(
            public_id, resource_type='image', type='upload', format=fmt, secure=True)[0]

    def cloud_url(self, name):
        """Direct Cloudinary URL. Only ever handed out after a permission check."""
        if self.is_private(name):
            return cloudinary.utils.cloudinary_url(
                name, resource_type='raw', type='upload', secure=True)[0]
        return self.url(name)

    def delete(self, name):
        try:
            if self.is_private(name):
                cloudinary.uploader.destroy(name, resource_type='raw', invalidate=True)
            else:
                public_id, _ = self._public_id_and_format(name)
                cloudinary.uploader.destroy(public_id, resource_type='image', invalidate=True)
        except Exception:
            logger.exception('Cloudinary delete failed for %s', name)

    def _open(self, name, mode='rb'):
        with urllib.request.urlopen(self.cloud_url(name), timeout=15) as resp:  # noqa: S310
            return ContentFile(resp.read(), name=name)

    def size(self, name):
        raise NotImplementedError('CloudinaryMediaStorage does not track file sizes')
