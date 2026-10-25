from django.db import transaction
from django.utils import timezone

from courses.models import Course, Enrollment, Lesson

from .models import LearningProgress, LessonProgress


@transaction.atomic
def start_course(learner, course):
    now = timezone.now()
    progress, created = LearningProgress.objects.get_or_create(
        learner=learner,
        course=course,
        defaults={
            "status": LearningProgress.Status.IN_PROGRESS,
            "started_at": now,
            "last_accessed_at": now,
        },
    )
    if not created:
        progress.last_accessed_at = now
        update_fields = ["last_accessed_at", "updated_at"]
        if progress.started_at is None:
            progress.started_at = now
            update_fields.append("started_at")
        if progress.status == LearningProgress.Status.NOT_STARTED:
            progress.status = LearningProgress.Status.IN_PROGRESS
            update_fields.append("status")
        progress.save(update_fields=update_fields)
    return progress, created


@transaction.atomic
def complete_lesson(learner, lesson: Lesson):
    now = timezone.now()
    lesson_progress, created = LessonProgress.objects.get_or_create(
        learner=learner,
        lesson=lesson,
        defaults={
            "is_completed": True,
            "started_at": now,
            "completed_at": now,
            "last_accessed_at": now,
        },
    )
    if not created:
        update_fields = ["last_accessed_at", "updated_at"]
        lesson_progress.last_accessed_at = now
        if not lesson_progress.is_completed:
            lesson_progress.is_completed = True
            lesson_progress.completed_at = now
            update_fields.extend(["is_completed", "completed_at"])
        if lesson_progress.started_at is None:
            lesson_progress.started_at = now
            update_fields.append("started_at")
        lesson_progress.save(update_fields=update_fields)

    course_progress, _ = start_course(learner, lesson.course)
    recalculate_course_progress(learner, lesson.course, progress=course_progress)
    if course_progress.status == LearningProgress.Status.COMPLETED:
        Enrollment.objects.filter(
            user=learner,
            course=lesson.course,
            status=Enrollment.Status.ACTIVE,
        ).update(
            status=Enrollment.Status.COMPLETED,
            completed_at=course_progress.completed_at,
        )
    return lesson_progress


def track_video_activity(learner, video_id, *, completed=False):
    lessons = Lesson.objects.filter(
        video_id=video_id,
        course__status=Course.Status.PUBLISHED,
        course__enrollments__user=learner,
        course__enrollments__status=Enrollment.Status.ACTIVE,
    ).select_related("course").distinct()
    tracked = []
    courses = {}

    for lesson in lessons:
        if completed:
            complete_lesson(learner, lesson)
        else:
            start_course(learner, lesson.course)
        tracked.append(lesson)
        courses[lesson.course_id] = lesson.course

    progress_records = LearningProgress.objects.filter(
        learner=learner,
        course__in=courses.values(),
    ).select_related("course")
    return list(progress_records)


def recalculate_course_progress(learner, course: Course, progress=None):
    if progress is None:
        progress = LearningProgress.objects.get(learner=learner, course=course)

    total_lessons = course.lessons.count()
    completed_lessons = LessonProgress.objects.filter(
        learner=learner,
        lesson__course=course,
        is_completed=True,
    ).count()
    percentage = (
        min(100, completed_lessons * 100 // total_lessons)
        if total_lessons
        else 0
    )
    now = timezone.now()

    if total_lessons and completed_lessons >= total_lessons:
        progress.status = LearningProgress.Status.COMPLETED
        if progress.completed_at is None:
            progress.completed_at = now
    else:
        progress.status = (
            LearningProgress.Status.IN_PROGRESS
            if progress.started_at is not None or completed_lessons
            else LearningProgress.Status.NOT_STARTED
        )
        progress.completed_at = None

    progress.progress_percentage = percentage
    progress.save(
        update_fields=[
            "status",
            "progress_percentage",
            "completed_at",
            "updated_at",
        ]
    )
    return progress
