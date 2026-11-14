from django.urls import path
from . import resume_views as views_resume
from . import views

urlpatterns = [
    path('profile/',      views.profile_view,      name='profile'),
    path('edit-profile/', views.edit_profile_view, name='edit_profile'),
    path('resume/<path:name>', views.resume_download_view, name='resume_download'),

    # Resume Builder
    path('resume-builder/',                              views_resume.resume_builder_view,        name='resume_builder'),
    path('resume-builder/preview.pdf',                   views_resume.resume_preview_pdf_view,    name='resume_preview_pdf'),
    path('resume-builder/generate/',                     views_resume.resume_generate_view,       name='resume_generate'),
    path('resume-builder/<str:kind>/save/',              views_resume.resume_entry_save_view,     name='resume_entry_add'),
    path('resume-builder/<str:kind>/<int:pk>/save/',     views_resume.resume_entry_save_view,     name='resume_entry_edit'),
    path('resume-builder/<str:kind>/<int:pk>/delete/',   views_resume.resume_entry_delete_view,   name='resume_entry_delete'),
    path('resume-builder/<str:kind>/<int:pk>/<str:direction>/', views_resume.resume_entry_move_view, name='resume_entry_move'),
]
