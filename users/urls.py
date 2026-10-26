from django.urls import path
from .views import register_view, dashboard_redirect_view

urlpatterns = [
    path("register/", register_view, name="register"),
    path("dashboard/", dashboard_redirect_view, name="dashboard_redirect"),
]
