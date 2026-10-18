from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, AuditLog

admin.site.register(User, UserAdmin)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target', 'ip_address')
    list_filter = ('action',)
    readonly_fields = ('actor', 'action', 'target', 'details', 'ip_address', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
