from django.contrib import admin
from .models import Announcement, AnnouncementReceipt


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'audience', 'recipients_count', 'is_pinned', 'created_at')
    list_filter = ('audience', 'is_pinned')
    search_fields = ('title', 'message')


admin.site.register(AnnouncementReceipt)
