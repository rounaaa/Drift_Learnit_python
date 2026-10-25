from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from courses.models import Course, Enrollment, Lesson

from .forms import ProgressFilterForm
from .models import LearningProgress, LessonProgress
from .services import complete_lesson, start_course, track_video_activity


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
        lessons = self.object.course.lessons.all()
        context["lessons"] = lessons
        context["completed_lesson_ids"] = set(
            LessonProgress.objects.filter(
                learner=self.request.user,
                lesson__course=self.object.course,
                is_completed=True,
            ).values_list("lesson_id", flat=True)
        )
        return context


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
        return context


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
                    "message": "",
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
