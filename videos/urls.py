from django.urls import path

from . import views

app_name = "videos"

urlpatterns = [
    path("<int:pk>/ai/generate/", views.VideoSummaryGenerateView.as_view(), name="ai_generate"),
    path("<int:pk>/ai/status/", views.VideoSummaryStatusView.as_view(), name="ai_status"),
    path("<int:pk>/subtitles/<str:lang>.vtt", views.VideoSubtitlesView.as_view(), name="subtitles"),
    path("<int:pk>/summary/pdf/", views.VideoSummaryPdfView.as_view(), name="summary_pdf"),
    path("ai/moderate/", views.VideoModerationEndpointView.as_view(), name="moderate"),
    path(
        "admin/delete-pending/",
        views.AdminDeletePendingVideosView.as_view(),
        name="admin_delete_pending",
    ),
    path("", views.VideoListView.as_view(), name="video_list"),
    path("feed/", views.LearnerVideoFeedView.as_view(), name="learner_feed"),
    path("create/", views.VideoCreateView.as_view(), name="video_create"),
    path("mine/", views.CreatorVideoListView.as_view(), name="my_videos"),
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/create/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/", views.CategoryDetailView.as_view(), name="category_detail"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_edit"),
    path("categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),
    path("<int:pk>/", views.VideoDetailView.as_view(), name="video_detail"),
    path("<int:pk>/edit/", views.VideoUpdateView.as_view(), name="video_edit"),
    path("<int:pk>/delete/", views.VideoDeleteView.as_view(), name="video_delete"),
    path("<int:pk>/toggle-status/", views.VideoPublishToggleView.as_view(), name="video_toggle_status"),
]
