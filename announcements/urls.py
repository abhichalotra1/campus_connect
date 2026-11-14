from django.urls import path
from . import views

urlpatterns = [
    path('',                       views.announcement_list_view,        name='announcements'),
    path('new/',                   views.announcement_create_view,      name='announcement_create'),
    path('audience-count/',        views.announcement_audience_count_view, name='announcement_audience_count'),
    path('<int:pk>/delete/',       views.announcement_delete_view,      name='announcement_delete'),
    path('<int:pk>/toggle-pin/',   views.announcement_toggle_pin_view,  name='announcement_toggle_pin'),
]
