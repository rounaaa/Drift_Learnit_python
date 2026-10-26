from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from courses.models import Lesson

from .models import LearningProgress
from .services import recalculate_course_progress


@receiver(pre_save, sender=Lesson)
def remember_previous_course(sender, instance, **kwargs):
    if instance.pk:
        instance._previous_course_id = (
            sender.objects.filter(pk=instance.pk)
            .values_list("course_id", flat=True)
            .first()
        )
    else:
        instance._previous_course_id = None


def recalculate_courses(course_ids):
    for course_id in filter(None, set(course_ids)):
        progress_records = LearningProgress.objects.filter(
            course_id=course_id
        ).select_related("course", "learner")
        for progress in progress_records:
            recalculate_course_progress(
                progress.learner,
                progress.course,
                progress=progress,
            )


@receiver(post_save, sender=Lesson)
def recalculate_after_lesson_save(sender, instance, **kwargs):
    recalculate_courses(
        [instance.course_id, getattr(instance, "_previous_course_id", None)]
    )


@receiver(post_delete, sender=Lesson)
def recalculate_after_lesson_delete(sender, instance, **kwargs):
    recalculate_courses([instance.course_id])
