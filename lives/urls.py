from django.urls import path

from . import views

urlpatterns = [
    path("", views.live_list_view, name="live_list"),
    path("monitoring/", views.live_monitoring_view, name="live_monitoring"),
    path("recommendations/", views.live_recommendations_view, name="live_recommendations"),
    path("<int:pk>/summary/generate/", views.live_generate_summary_view, name="live_generate_summary"),
    path("<int:pk>/", views.live_detail_view, name="live_detail"),
    path("create/", views.live_create_view, name="live_create"),
    path("<int:pk>/edit/", views.live_edit_view, name="live_edit"),
    path("<int:pk>/cancel/", views.live_cancel_view, name="live_cancel"),
    path("<int:pk>/register/", views.live_register_view, name="live_register"),
    path("<int:pk>/unregister/", views.live_unregister_view, name="live_unregister"),
    path("<int:pk>/attendance/", views.live_attendance_view, name="live_attendance"),
    path("<int:pk>/status/", views.live_status_update_view, name="live_status_update"),
]
