from django.urls import path
from . import views

urlpatterns = [
    # Recruiter Specific Routes
    path('recruiter-dashboard/', views.recruiter_dashboard_view, name='recruiter_dashboard'),
    path('my-applicants/',       views.recruiter_applicants_view, name='recruiter_applicants'),
    
    # Drive Management
    path('edit-drive/<int:pk>/',     views.edit_drive_view,        name='edit_drive'),
    path('delete-drive/<int:pk>/',   views.delete_drive_view,      name='delete_drive'),
    path('company/<int:user_id>/',   views.company_profile_view,   name='company_profile'), # NEW LINE
    
    # General Drive Routes
    path('',                         views.drive_list_view,        name='drive_list'),
    path('<int:pk>/',                views.drive_detail_view,      name='drive_detail'),
    path('apply/<int:pk>/',          views.apply_view,             name='apply'),
    path('post-drive/',              views.post_drive_view,        name='post_drive'),
    
    # Student Routes
    path('my-applications/',         views.my_applications_view,   name='my_applications'),
    path('withdraw/<int:pk>/',       views.withdraw_view,          name='withdraw'),
    path('my-interviews/',           views.my_interviews_view,     name='my_interviews'),
    
    # Admin/Recruiter Interview Route
    path('schedule/<int:app_id>/',   views.schedule_interview_view, name='schedule_interview'),

    # Bookmark URLs
    path('saved-jobs/',          views.saved_jobs_view,    name='saved_jobs'),
    path('save-drive/<int:pk>/', views.save_drive_view,    name='save_drive'),
    path('unsave-drive/<int:pk>/', views.unsave_drive_view, name='unsave_drive'),

        # Chat URLs
    path('chat/start/<int:application_id>/', views.get_or_create_chat_view, name='start_chat'),    
    path('chat/<int:conversation_id>/', views.chat_room_view, name='chat_room'),
    path('chat/<int:conversation_id>/fetch/', views.fetch_messages_api, name='chat_fetch'),
    path('chat/<int:conversation_id>/send/', views.send_message_api, name='chat_send'),
    path('chat/<int:conversation_id>/unlock/', views.unlock_student_chat, name='chat_unlock'),
]