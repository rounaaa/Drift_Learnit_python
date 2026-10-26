import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from courses.models import Course, Enrollment, Lesson

from .ai_service import AIServiceError, explain_wrong_answer
from .forms import ProgressFilterForm, QuizStartForm
from .models import LearningHistory, LearningProgress, LessonProgress, QuizAttempt
from .reporting import build_learning_report
from .report_ai_service import ProgressReportAIError, generate_progress_feedback
from .services import (
    complete_lesson,
    create_quiz_attempt,
    start_course,
    submit_quiz_attempt,
    track_lesson_video_activity,
    track_video_activity,
)

logger = logging.getLogger(__name__)


class LearnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return getattr(self.request.user, "role", None) == "LEARNER"


class ProgressDashboardView(LearnerRequiredMixin, TemplateView):
    template_name = "progress/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        learner = self.request.user
        progress = LearningProgress.objects.filter(learner=learner).select_related(
            "course"
        )
        context.update(
            {
                "recent_progress": progress.order_by("-last_accessed_at")[:5],
                "in_progress_count": progress.filter(
                    status=LearningProgress.Status.IN_PROGRESS
                ).count(),
                "completed_count": progress.filter(
                    status=LearningProgress.Status.COMPLETED
                ).count(),
                "active_enrollments": Enrollment.objects.filter(
                    user=learner,
                    status=Enrollment.Status.ACTIVE,
                    course__status=Course.Status.PUBLISHED,
                )
                .select_related("course")
                .order_by("-enrolled_at"),
            }
        )
        return context


class LearningProgressListView(LearnerRequiredMixin, ListView):
    model = LearningProgress
    template_name = "progress/course_list.html"
    context_object_name = "progress_list"
    paginate_by = 10

    def get_queryset(self):
        self.filter_form = ProgressFilterForm(self.request.GET)
        queryset = LearningProgress.objects.filter(
            learner=self.request.user
        ).select_related("course")
        if self.filter_form.is_valid() and self.filter_form.cleaned_data["status"]:
            queryset = queryset.filter(status=self.filter_form.cleaned_data["status"])
        return queryset.order_by("-last_accessed_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


class LearningProgressDetailView(LearnerRequiredMixin, DetailView):
    model = LearningProgress
    template_name = "progress/detail.html"
    context_object_name = "course_progress"

    def get_queryset(self):
        return LearningProgress.objects.filter(
            learner=self.request.user
        ).select_related("course", "course__creator")

    def get_object(self, queryset=None):
        progress = super().get_object(queryset)
        now = timezone.now()
        progress.last_accessed_at = now
        progress.save(update_fields=["last_accessed_at", "updated_at"])
        return progress

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lessons = list(self.object.course.lessons.select_related("video").all())
        context["lessons"] = lessons
        context["completed_lesson_ids"] = set(
            LessonProgress.objects.filter(
                learner=self.request.user,
                lesson__course=self.object.course,
                is_completed=True,
            ).values_list("lesson_id", flat=True)
        )
        context["total_lessons_count"] = len(lessons)
        context["completed_lessons_count"] = len(context["completed_lesson_ids"])
        context["learning_report"] = build_learning_report(
            self.request.user,
            self.object.course,
            lessons,
            context["completed_lesson_ids"],
        )
        context["next_lesson_id"] = next(
            (
                lesson.pk
                for lesson in lessons
                if lesson.pk not in context["completed_lesson_ids"]
            ),
            None,
        )
        context["recent_quiz_attempts"] = self.object.course.progress_quiz_attempts.filter(
            learner=self.request.user
        )[:5]
        context["quiz_form"] = QuizStartForm()
        return context


class LearningReportAIView(LearnerRequiredMixin, View):
    """Generate optional Gemini advice for the authenticated learner's course."""

    http_method_names = ["post"]

    def post(self, request, pk):
        progress = get_object_or_404(
            LearningProgress.objects.select_related("course").filter(
                learner=request.user
            ),
            pk=pk,
        )
        lessons = list(progress.course.lessons.order_by("order"))
        completed_lesson_ids = set(
            LessonProgress.objects.filter(
                learner=request.user,
                lesson__course=progress.course,
                is_completed=True,
            ).values_list("lesson_id", flat=True)
        )
        report = build_learning_report(
            request.user, progress.course, lessons, completed_lesson_ids
        )
        try:
            feedback = generate_progress_feedback(report, progress.course, lessons)
        except ProgressReportAIError as exc:
            logger.info("Gemini progress feedback unavailable for course %s", progress.course_id)
            return JsonResponse(
                {"success": False, "message": str(exc)},
                status=503,
            )
        return JsonResponse({"success": True, "feedback": feedback})


class LearningHistoryView(LearnerRequiredMixin, ListView):
    model = LearningProgress
    template_name = "progress/history.html"
    context_object_name = "history"
    paginate_by = 10

    def get_queryset(self):
        self.filter_form = ProgressFilterForm(self.request.GET)
        queryset = LearningProgress.objects.filter(
            learner=self.request.user
        ).select_related("course")
        if self.filter_form.is_valid() and self.filter_form.cleaned_data["status"]:
            queryset = queryset.filter(status=self.filter_form.cleaned_data["status"])
        return queryset.order_by("-last_accessed_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["activities"] = LearningHistory.objects.filter(
            user=self.request.user
        ).select_related("course", "lesson", "video")[:30]
        return context


class LearningActivityHistoryView(LearnerRequiredMixin, ListView):
    model = LearningHistory
    template_name = "progress/activity_history.html"
    context_object_name = "activities"
    paginate_by = 20

    def get_queryset(self):
        return LearningHistory.objects.filter(
            user=self.request.user
        ).select_related("course", "lesson", "video")


class StartCourseView(LearnerRequiredMixin, View):
    def post(self, request, pk):
        course = get_object_or_404(
            Course,
            pk=pk,
            status=Course.Status.PUBLISHED,
        )
        is_enrolled = Enrollment.objects.filter(
            user=request.user,
            course=course,
            status=Enrollment.Status.ACTIVE,
        ).exists()
        if not is_enrolled:
            messages.error(
                request,
                "Vous devez être inscrit au cours pour démarrer ou reprendre votre progression.",
            )
            return redirect("course_detail", pk=course.pk)

        progress, created = start_course(request.user, course)
        if created:
            messages.success(request, f"Votre suivi du cours « {course.title} » a commencé.")
        else:
            messages.success(request, f"Vous reprenez le cours « {course.title} ».")
        return redirect("progress:detail", pk=progress.pk)


class CompleteLessonView(LearnerRequiredMixin, View):
    def post(self, request, lesson_pk):
        lesson = get_object_or_404(
            Lesson.objects.select_related("course"),
            pk=lesson_pk,
            course__status=Course.Status.PUBLISHED,
        )
        is_enrolled = Enrollment.objects.filter(
            user=request.user,
            course=lesson.course,
            status=Enrollment.Status.ACTIVE,
        ).exists()
        if not is_enrolled:
            messages.error(
                request,
                "Vous devez être inscrit au cours pour valider une leçon.",
            )
            return redirect("course_detail", pk=lesson.course.pk)

        complete_lesson(request.user, lesson)
        messages.success(request, f"Leçon « {lesson.title} » marquée comme terminée.")
        return redirect(
            "progress:detail",
            pk=get_object_or_404(
                LearningProgress,
                learner=request.user,
                course=lesson.course,
            ).pk,
        )


class TrackVideoActivityView(LearnerRequiredMixin, View):
    def post(self, request, video_pk):
        action = request.POST.get("action")
        if action not in {"started", "completed"}:
            return JsonResponse(
                {"success": False, "message": "Action de suivi invalide."},
                status=400,
            )

        completed = action == "completed"
        tracked_progress = track_video_activity(
            request.user,
            video_pk,
            completed=completed,
        )
        if not tracked_progress:
            return JsonResponse(
                {
                    "success": True,
                    "tracked": False,
                    "message": (
                        "La vidéo n'est pas liée à une leçon suivie unique."
                    ),
                }
            )
        return JsonResponse(
            {
                "success": True,
                "tracked": True,
                "message": (
                    "Leçon terminée et progression mise à jour."
                    if completed
                    else "Votre progression a été enregistrée."
                ),
                "courses": [
                    {
                        "id": progress.pk,
                        "title": progress.course.title,
                        "percentage": progress.progress_percentage,
                        "status": progress.status,
                    }
                    for progress in tracked_progress
                ],
            }
        )


class TrackLessonVideoActivityView(LearnerRequiredMixin, View):
    def post(self, request, lesson_pk):
        action = request.POST.get("action")
        if action not in {"started", "completed"}:
            return JsonResponse(
                {"success": False, "message": "Action de suivi invalide."},
                status=400,
            )

        lesson = get_object_or_404(
            Lesson.objects.select_related("course", "video"),
            pk=lesson_pk,
        )
        progress = track_lesson_video_activity(
            request.user,
            lesson,
            completed=action == "completed",
        )
        if progress is None:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Cette leçon ne peut pas être suivie avec votre inscription actuelle.",
                },
                status=403,
            )
        return JsonResponse(
            {
                "success": True,
                "message": (
                    "Leçon terminée et progression mise à jour."
                    if action == "completed"
                    else "Votre activité vidéo a été enregistrée."
                ),
                "progress_percentage": progress.progress_percentage,
                "status": progress.status,
                "lesson_id": lesson.pk,
            }
        )


class StartCourseQuizView(LearnerRequiredMixin, View):
    def post(self, request, course_pk):
        course = get_object_or_404(
            Course,
            pk=course_pk,
            status=Course.Status.PUBLISHED,
        )
        enrolled = Enrollment.objects.filter(
            user=request.user,
            course=course,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED],
        ).exists()
        if not enrolled:
            messages.error(request, "Vous devez être inscrit à ce cours pour passer son quiz.")
            return redirect("course_catalog")

        form = QuizStartForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choisissez un nombre de questions valide (3, 5 ou 10).")
            progress = LearningProgress.objects.filter(
                learner=request.user,
                course=course,
            ).first()
            if progress:
                return redirect("progress:detail", pk=progress.pk)
            return redirect("course_detail", pk=course.pk)

        try:
            attempt = create_quiz_attempt(
                request.user,
                course,
                num_questions=form.cleaned_data["num_questions"],
            )
        except (RuntimeError, ValueError) as exc:
            messages.error(request, f"Impossible de générer le quiz : {exc}")
            progress = LearningProgress.objects.filter(
                learner=request.user,
                course=course,
            ).first()
            if progress:
                return redirect("progress:detail", pk=progress.pk)
            return redirect("course_detail", pk=course.pk)

        messages.success(request, "Votre quiz est prêt. Bonne chance !")
        return redirect("progress:quiz_attempt", pk=attempt.pk)


class QuizAttemptDetailView(LearnerRequiredMixin, DetailView):
    model = QuizAttempt
    template_name = "progress/quiz_attempt.html"
    context_object_name = "attempt"

    def get_queryset(self):
        return QuizAttempt.objects.filter(
            learner=self.request.user
        ).select_related("course")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["course_progress"] = LearningProgress.objects.filter(
            learner=self.request.user,
            course=self.object.course,
        ).first()
        context["questions"] = [
            {
                "text": question["question"],
                "options": [
                    {"index": option_index, "text": option}
                    for option_index, option in enumerate(question["options"])
                ],
                "explanation": question.get("explanation", ""),
                "correct_index": (
                    question["correct_index"]
                    if self.object.status == QuizAttempt.Status.COMPLETED
                    else None
                ),
                "answer": self.object.answers.get(str(index)),
                "ai_explanation": question.get("ai_explanation", ""),
                "can_explain": (
                    self.object.status == QuizAttempt.Status.COMPLETED
                    and self.object.answers.get(str(index)) is not None
                    and self.object.answers.get(str(index))
                    != question["correct_index"]
                    and 0
                    <= self.object.answers.get(str(index))
                    < len(question["options"])
                ),
            }
            for index, question in enumerate(self.object.questions)
        ]
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.status == QuizAttempt.Status.COMPLETED:
            messages.info(request, "Cette tentative a déjà été corrigée.")
            return redirect("progress:quiz_attempt", pk=self.object.pk)

        answers = {
            str(index): request.POST.get(f"answer_{index}", "")
            for index in range(self.object.total_questions)
        }
        attempt, submitted = submit_quiz_attempt(self.object, answers)
        if submitted:
            messages.success(
                request,
                f"Quiz corrigé : {attempt.score}/{attempt.total_questions}.",
            )
        return redirect("progress:quiz_attempt", pk=attempt.pk)


class ExplainQuizAnswerView(LearnerRequiredMixin, View):
    def post(self, request, pk, question_index):
        attempt = get_object_or_404(
            QuizAttempt,
            pk=pk,
            learner=request.user,
        )
        if attempt.status != QuizAttempt.Status.COMPLETED:
            return JsonResponse(
                {"success": False, "message": "Terminez le quiz avant de demander une explication."},
                status=409,
            )
        if question_index < 0 or question_index >= len(attempt.questions):
            return JsonResponse(
                {"success": False, "message": "Question introuvable."},
                status=404,
            )

        question = attempt.questions[question_index]
        try:
            selected_index = int(attempt.answers.get(str(question_index), -1))
        except (TypeError, ValueError):
            selected_index = -1
        if not 0 <= selected_index < len(question["options"]):
            return JsonResponse(
                {"success": False, "message": "Aucune réponse valide n'est enregistrée pour cette question."},
                status=400,
            )
        if selected_index == question["correct_index"]:
            return JsonResponse(
                {"success": False, "message": "Cette réponse est correcte : aucune explication d'erreur n'est nécessaire."},
                status=400,
            )
        if question.get("ai_explanation"):
            return JsonResponse(
                {"success": True, "explanation": question["ai_explanation"]}
            )

        try:
            explanation = explain_wrong_answer(question, selected_index)
        except AIServiceError as exc:
            logger.warning(
                "Unable to generate quiz explanation for attempt %s, question %s (%s)",
                attempt.pk,
                question_index,
                type(exc).__name__,
            )
            return JsonResponse(
                {"success": False, "message": str(exc)},
                status=503,
            )

        with transaction.atomic():
            attempt = QuizAttempt.objects.select_for_update().get(
                pk=attempt.pk,
                learner=request.user,
            )
            question = attempt.questions[question_index]
            explanation = question.get("ai_explanation") or explanation
            question["ai_explanation"] = explanation
            attempt.questions[question_index] = question
            attempt.save(update_fields=["questions"])

        return JsonResponse({"success": True, "explanation": explanation})
