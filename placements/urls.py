from django.urls import path
from . import views

urlpatterns = [
    path('my-applicants/', views.recruiter_applicants_view, name='recruiter_applicants'),
    path('',                         views.drive_list_view,        name='drive_list'),
    path('<int:pk>/',                views.drive_detail_view,      name='drive_detail'),
    path('apply/<int:pk>/',          views.apply_view,             name='apply'),
    path('my-applications/',         views.my_applications_view,   name='my_applications'),
    path('withdraw/<int:pk>/',       views.withdraw_view,          name='withdraw'),
    path('post-drive/',              views.post_drive_view,        name='post_drive'),
    path('my-interviews/',           views.my_interviews_view,     name='my_interviews'),
    path('schedule/<int:app_id>/',   views.schedule_interview_view, name='schedule_interview'),
    path('my-applicants/', views.recruiter_applicants_view, name='recruiter_applicants'),
]

