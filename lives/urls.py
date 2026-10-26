from django.urls import path

from . import views

urlpatterns = [
    path("", views.live_list_view, name="live_list"),
    path("<int:pk>/", views.live_detail_view, name="live_detail"),
    path("create/", views.live_create_view, name="live_create"),
    path("<int:pk>/edit/", views.live_update_view, name="live_edit"),
    path("<int:pk>/cancel/", views.live_cancel_view, name="live_cancel"),
    path("<int:pk>/register/", views.live_register_view, name="live_register"),
    path("<int:pk>/unregister/", views.live_unregister_view, name="live_unregister"),
    path("<int:pk>/attendance/", views.live_attendance_list_view, name="live_attendance_list"),
    path("<int:pk>/attendance/create/", views.live_attendance_create_view, name="live_attendance_create"),
    path("<int:pk>/status/", views.live_status_update_view, name="live_status_update"),
]
