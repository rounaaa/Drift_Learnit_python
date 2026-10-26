from django.db import transaction
from django.utils import timezone

from courses.models import Course, Enrollment, Lesson

from .models import LearningHistory, LearningProgress, LessonProgress, QuizAttempt


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
    if created:
        LearningHistory.objects.create(
            user=learner,
            course=course,
            event_type=LearningHistory.EventType.COURSE_STARTED,
        )
    else:
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
def start_lesson_video(learner, lesson: Lesson):
    now = timezone.now()
    lesson_progress, created = LessonProgress.objects.get_or_create(
        learner=learner,
        lesson=lesson,
        defaults={"started_at": now, "last_accessed_at": now},
    )
    if not created:
        lesson_progress.last_accessed_at = now
        update_fields = ["last_accessed_at", "updated_at"]
        if lesson_progress.started_at is None:
            lesson_progress.started_at = now
            update_fields.append("started_at")
        lesson_progress.save(update_fields=update_fields)

    course_progress, _ = start_course(learner, lesson.course)
    course_progress.last_accessed_at = now
    course_progress.save(update_fields=["last_accessed_at", "updated_at"])
    LearningHistory.objects.create(
        user=learner,
        course=lesson.course,
        lesson=lesson,
        video=lesson.video,
        event_type=LearningHistory.EventType.VIDEO_STARTED,
        source=LearningHistory.Source.VIDEO,
    )
    return lesson_progress


@transaction.atomic
def complete_lesson(learner, lesson: Lesson, *, source=LearningHistory.Source.MANUAL):
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
    newly_completed = created or not lesson_progress.is_completed
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
    course_progress.last_accessed_at = now
    course_progress.save(update_fields=["last_accessed_at", "updated_at"])
    if newly_completed:
        LearningHistory.objects.create(
            user=learner,
            course=lesson.course,
            lesson=lesson,
            video=lesson.video if source == LearningHistory.Source.VIDEO else None,
            event_type=LearningHistory.EventType.LESSON_COMPLETED,
            source=source,
        )
    recalculate_course_progress(
        learner,
        lesson.course,
        progress=course_progress,
        source=source,
    )
    return lesson_progress


def track_video_activity(learner, video_id, *, completed=False):
    lessons = Lesson.objects.filter(
        video_id=video_id,
        video__status="PUBLISHED",
        course__status=Course.Status.PUBLISHED,
        course__enrollments__user=learner,
        course__enrollments__status=Enrollment.Status.ACTIVE,
    ).select_related("course").distinct()
    lesson = lessons.first()
    if lesson is None or lessons.count() != 1:
        return []
    if completed:
        complete_lesson(learner, lesson, source=LearningHistory.Source.VIDEO)
    else:
        start_lesson_video(learner, lesson)
    return list(LearningProgress.objects.filter(
        learner=learner,
        course=lesson.course,
    ).select_related("course"))


@transaction.atomic
def track_lesson_video_activity(learner, lesson, *, completed=False):
    enrollment = Enrollment.objects.filter(
        user=learner,
        course=lesson.course,
        status=Enrollment.Status.ACTIVE,
    ).exists()
    if (
        not enrollment
        or lesson.course.status != Course.Status.PUBLISHED
        or lesson.video_id is None
        or lesson.video.status != "PUBLISHED"
    ):
        return None

    if completed:
        complete_lesson(learner, lesson, source=LearningHistory.Source.VIDEO)
    else:
        start_lesson_video(learner, lesson)
    return LearningProgress.objects.get(learner=learner, course=lesson.course)


def recalculate_course_progress(
    learner,
    course: Course,
    progress=None,
    *,
    source=LearningHistory.Source.COURSE_UPDATE,
):
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

    previous_status = progress.status
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
    _sync_enrollment_status(learner, course, progress)
    if (
        progress.status == LearningProgress.Status.COMPLETED
        and previous_status != LearningProgress.Status.COMPLETED
    ):
        LearningHistory.objects.create(
            user=learner,
            course=course,
            event_type=LearningHistory.EventType.COURSE_COMPLETED,
            source=source,
        )
    return progress


def _sync_enrollment_status(learner, course, progress):
    enrollments = Enrollment.objects.filter(
        user=learner,
        course=course,
        status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED],
    )
    if progress.status == LearningProgress.Status.COMPLETED:
        enrollments.update(
            status=Enrollment.Status.COMPLETED,
            completed_at=progress.completed_at,
        )
    else:
        enrollments.filter(status=Enrollment.Status.COMPLETED).update(
            status=Enrollment.Status.ACTIVE,
            completed_at=None,
        )


def create_quiz_attempt(learner, course, *, num_questions=5):
    from .ai_service import generate_quiz

    if not 3 <= num_questions <= 10:
        raise ValueError("Le quiz doit contenir entre 3 et 10 questions.")

    quiz = generate_quiz(course, num_questions)
    if not isinstance(quiz, dict):
        raise ValueError("Le générateur n'a pas retourné un quiz valide.")
    questions = quiz.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Le générateur n'a pas retourné de questions valides.")

    validated_questions = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Le générateur a retourné une question mal formée.")
        options = question.get("options")
        answer_index = question.get("correct_index")
        if (
            not isinstance(question.get("question"), str)
            or not isinstance(options, list)
            or len(options) < 2
            or not all(isinstance(option, str) for option in options)
            or not isinstance(answer_index, int)
            or isinstance(answer_index, bool)
            or answer_index < 0
            or answer_index >= len(options)
        ):
            raise ValueError("Le générateur a retourné une question mal formée.")
        validated_questions.append(
            {
                "question": question["question"],
                "options": options,
                "correct_index": answer_index,
                "explanation": str(question.get("explanation", "")),
            }
        )

    attempt = QuizAttempt.objects.create(
        learner=learner,
        course=course,
        questions=validated_questions,
        total_questions=len(validated_questions),
    )
    LearningHistory.objects.create(
        user=learner,
        course=course,
        event_type=LearningHistory.EventType.QUIZ_STARTED,
        source=LearningHistory.Source.AI,
        details={"attempt_id": attempt.pk},
    )
    return attempt


@transaction.atomic
def submit_quiz_attempt(attempt, answers):
    attempt = QuizAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.status == QuizAttempt.Status.COMPLETED:
        return attempt, False

    score = 0
    submitted_answers = {}
    for index, question in enumerate(attempt.questions):
        raw_answer = answers.get(str(index), "")
        try:
            answer = int(raw_answer)
        except (TypeError, ValueError):
            answer = -1
        submitted_answers[str(index)] = answer
        if answer == question["correct_index"]:
            score += 1

    attempt.answers = submitted_answers
    attempt.score = score
    attempt.status = QuizAttempt.Status.COMPLETED
    attempt.completed_at = timezone.now()
    attempt.save(
        update_fields=["answers", "score", "status", "completed_at"]
    )
    LearningHistory.objects.create(
        user=attempt.learner,
        course=attempt.course,
        event_type=LearningHistory.EventType.QUIZ_COMPLETED,
        source=LearningHistory.Source.AI,
        details={
            "attempt_id": attempt.pk,
            "score": score,
            "total_questions": attempt.total_questions,
        },
    )
    return attempt, True
