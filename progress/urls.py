from django.urls import path

from . import views

app_name = "progress"

urlpatterns = [
    path("", views.ProgressDashboardView.as_view(), name="dashboard"),
    path("courses/", views.LearningProgressListView.as_view(), name="course_list"),
    path("courses/<int:pk>/", views.LearningProgressDetailView.as_view(), name="detail"),
    path(
        "courses/<int:pk>/report/ai/",
        views.LearningReportAIView.as_view(),
        name="ai_report",
    ),
    path("history/", views.LearningHistoryView.as_view(), name="history"),
    path(
        "history/activities/",
        views.LearningActivityHistoryView.as_view(),
        name="activity_history",
    ),
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
    path(
        "lessons/<int:lesson_pk>/video-activity/",
        views.TrackLessonVideoActivityView.as_view(),
        name="lesson_video_activity",
    ),
    path(
        "courses/<int:course_pk>/quiz/start/",
        views.StartCourseQuizView.as_view(),
        name="start_quiz",
    ),
    path(
        "quiz/attempts/<int:pk>/",
        views.QuizAttemptDetailView.as_view(),
        name="quiz_attempt",
    ),
    path(
        "quiz/attempts/<int:pk>/questions/<int:question_index>/explain/",
        views.ExplainQuizAnswerView.as_view(),
        name="explain_quiz_answer",
    ),
]
