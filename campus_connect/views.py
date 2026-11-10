from django.shortcuts import render, redirect
from django.templatetags.static import static

def custom_404(request, exception):
    return render(request, '404.html', status=404)

def custom_500(request):
    return render(request, '500.html', status=500)

def custom_403(request, exception):
    return render(request, '403.html', status=403)

def favicon(request):
    return redirect(static('favicon.ico'), permanent=True)
