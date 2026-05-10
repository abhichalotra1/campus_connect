"""
accounts/apps.py
─────────────────
Connects Django signals when the accounts app is ready.
"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        import accounts.signals  # noqa — registers the post_save signal