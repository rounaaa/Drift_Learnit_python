from django.urls import path

from . import views

app_name = "progress"

urlpatterns = [
    path("", views.ProgressDashboardView.as_view(), name="dashboard"),
    path("courses/", views.LearningProgressListView.as_view(), name="course_list"),
    path("courses/<int:pk>/", views.LearningProgressDetailView.as_view(), name="detail"),
    path("history/", views.LearningHistoryView.as_view(), name="history"),
    path("courses/<int:pk>/start/", views.StartCourseView.as_view(), name="start_course"),
    path(
        "lessons/<int:lesson_pk>/complete/",
        views.CompleteLessonView.as_view(),
        name="complete_lesson",
    ),
    path(
        "videos/<int:video_pk>/activity/",
        views.TrackVideoActivityView.as_view(),
        name="video_activity",
    ),
]
