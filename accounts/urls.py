from django.urls import path
from . import views

urlpatterns = [
    path('stats/',                       views.stats_view,              name='stats'),
    path('export-students/',             views.export_students_csv,     name='export_students'),
    path('export-students-excel/',       views.export_students_excel,   name='export_students_excel'),
    path('search-students/',             views.search_students_view,    name='search_students'),
    path('register/',                    views.register_view,           name='register'),
    path('login/',                       views.login_view,              name='login'),
    path('logout/',                      views.logout_view,             name='logout'),
    path('admin-dashboard/',             views.admin_dashboard_view,    name='admin_dashboard'),
    path('update-application/<int:pk>/', views.update_application_status, name='update_application'),
    path('verification-status/',           views.verification_status_view,   name='verification_status'),
    path('request-verification/',          views.request_verification_view,  name='request_verification'),
    path('verify-recruiter/<int:user_id>/', views.admin_verify_recruiter,    name='admin_verify_recruiter'),
    
    # New Admin Moderation Routes
    path('admin-toggle-drive/<int:drive_id>/', views.admin_toggle_drive_status, name='admin_toggle_drive'),
    path('admin-toggle-user/<int:user_id>/',   views.admin_toggle_user_status,  name='admin_toggle_user'),
]