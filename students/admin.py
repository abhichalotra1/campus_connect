from django.contrib import admin
from .models import Achievement, Education, Experience, Project, StudentProfile

admin.site.register(StudentProfile)
admin.site.register(Education)
admin.site.register(Experience)
admin.site.register(Project)
admin.site.register(Achievement)
