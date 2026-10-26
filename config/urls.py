"""
URL configuration for learnit project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('videos/', include('videos.urls')),
    path('recherche/', include('personalization.urls')),
    path('', include('courses.urls')),
    path('', include('users.urls')),   
    path('progression/', include('progress.urls')),
    path('', include('agent.urls')),
    path('gamification/', include('gamification.urls')),
    path('lives/', include('lives.urls')),
    path('', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
