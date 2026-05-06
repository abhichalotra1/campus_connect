from django.urls import path
from . import views

urlpatterns = [
    path('profile/',      views.profile_view,      name='profile'),
    path('edit-profile/', views.edit_profile_view, name='edit_profile'),
]