from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts import views as account_views
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Our Custom Accounts App (Login, Register, Dashboard, Stats, etc.)
    path('accounts/', include('accounts.urls')),
    
    # Django Allauth (Google/GitHub OAuth)
    # This MUST come after our custom accounts urls so our register page takes priority
    path('auth/', include('allauth.urls')),
    
    # Redirect Allauth's default /accounts/signup/ to our beautiful custom /accounts/register/
    path('accounts/signup/', RedirectView.as_view(url='/accounts/register/', permanent=True)),

    # Students App
    path('students/', include('students.urls')),
    
    # Placements App
    path('placements/', include('placements.urls')),
    
    # Notifications App
    path('notifications/', include('notifications.urls')),

    # Password Reset (Using Django's built-in views with our custom templates)
    path('password-change/', auth_views.PasswordChangeView.as_view(template_name='accounts/password_change.html'), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='accounts/password_change_done.html'), name='password_change_done'),
    path('password-reset/',
         auth_views.PasswordResetView.as_view(
             template_name='accounts/password_reset.html', # FIXED
             email_template_name='accounts/password_reset_email.html',
             subject_template_name='accounts/password_reset_subject.txt',   
         ),
         name='password_reset'),

    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='accounts/password_reset_done.html'
         ),
         name='password_reset_done'),

    path('password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='accounts/password_reset_confirm.html'
         ),
         name='password_reset_confirm'),

    path('password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='accounts/password_reset_complete.html'
         ),
         name='password_reset_complete'),

    # Landing Page
    path('', account_views.landing_view, name='landing'),

    # Dashboard
    path('dashboard/', account_views.dashboard_view, name='dashboard'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)