"""Delete stored files that nothing refers to any more.

Without this, every replaced picture/resume and every deleted drive leaves its old file
behind (on Cloudinary that is storage you pay for, and old resumes stay reachable).

* Replacing or clearing a file field deletes the previous file once the save succeeded.
* Deleting a row deletes its files.
"""
import logging

from django.db import models, transaction
from django.db.models.signals import post_delete, post_save, pre_save

logger = logging.getLogger(__name__)


def _file_fields(model):
    return [f for f in model._meta.get_fields() if isinstance(f, models.FileField)]


def _delete_file(storage, name):
    try:
        storage.delete(name)
    except Exception:
        logger.exception('Could not delete stored file %s', name)


def remember_old_files(sender, instance, raw=False, **kwargs):
    fields = _file_fields(sender)
    if raw or not fields or not instance.pk:
        return
    old = sender._default_manager.filter(pk=instance.pk).first()
    if old is None:
        return
    instance._old_files = {f.name: (getattr(old, f.name).name or None) for f in fields}


def delete_replaced_files(sender, instance, created=False, **kwargs):
    old_files = instance.__dict__.pop('_old_files', None)
    if not old_files:
        return
    for field in _file_fields(sender):
        old_name = old_files.get(field.name)
        current = getattr(instance, field.name)
        if old_name and old_name != (current.name or None):
            transaction.on_commit(lambda s=field.storage, n=old_name: _delete_file(s, n))


def delete_files_of_deleted_row(sender, instance, **kwargs):
    for field in _file_fields(sender):
        file = getattr(instance, field.name)
        if file and file.name:
            transaction.on_commit(lambda s=field.storage, n=file.name: _delete_file(s, n))


def connect():
    pre_save.connect(remember_old_files, dispatch_uid='cc_remember_old_files')
    post_save.connect(delete_replaced_files, dispatch_uid='cc_delete_replaced_files')
    post_delete.connect(delete_files_of_deleted_row, dispatch_uid='cc_delete_row_files')
