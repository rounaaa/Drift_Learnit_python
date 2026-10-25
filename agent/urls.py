from django.urls import path
from . import views

urlpatterns = [
    # Chat principal (liste des sessions + dernière session)
    path("agent/", views.agent_chat_view, name="agent_chat"),

    # Session spécifique
    path("agent/session/<int:session_id>/", views.agent_chat_view, name="agent_chat_session"),

    # Actions
    path("agent/new/", views.new_session_view, name="agent_new_session"),
    path("agent/session/<int:session_id>/delete/", views.delete_session_view, name="agent_delete_session"),

    # AJAX : envoi de message
    path("agent/session/<int:session_id>/send/", views.send_message_view, name="agent_send_message"),
]
