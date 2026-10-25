import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def reject_unmappable_placeholder_rows(apps, schema_editor):
    LearningProgress = apps.get_model("progress", "LearningProgress")
    database = schema_editor.connection.alias
    if LearningProgress.objects.using(database).exists():
        raise RuntimeError(
            "The placeholder progress.LearningProgress table contains rows with no "
            "learner or course data. Resolve those rows before applying this migration."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0002_course_category_alter_course_description_and_more"),
        ("progress", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="learningprogress",
            name="status",
            field=models.CharField(
                choices=[
                    ("NOT_STARTED", "Non commencé"),
                    ("IN_PROGRESS", "En cours"),
                    ("COMPLETED", "Terminé"),
                ],
                default="NOT_STARTED",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="progress_percentage",
            field=models.PositiveSmallIntegerField(
                default=0,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="last_accessed_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="course",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="learning_progress",
                to="courses.course",
            ),
        ),
        migrations.AddField(
            model_name="learningprogress",
            name="learner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="course_learning_progress",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(reject_unmappable_placeholder_rows, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="learningprogress",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="learningprogress",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="learningprogress",
            name="course",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="learning_progress",
                to="courses.course",
            ),
        ),
        migrations.AlterField(
            model_name="learningprogress",
            name="learner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="course_learning_progress",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="learningprogress",
            constraint=models.UniqueConstraint(
                fields=("learner", "course"),
                name="unique_learner_course_progress",
            ),
        ),
        migrations.AddConstraint(
            model_name="learningprogress",
            constraint=models.CheckConstraint(
                condition=models.Q(progress_percentage__gte=0)
                & models.Q(progress_percentage__lte=100),
                name="learning_progress_percentage_0_100",
            ),
        ),
        migrations.AlterModelOptions(
            name="learningprogress",
            options={"ordering": ["-last_accessed_at"]},
        ),
        migrations.CreateModel(
            name="LessonProgress",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("is_completed", models.BooleanField(default=False)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_accessed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "learner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lesson_progress",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lesson",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="learning_progress",
                        to="courses.lesson",
                    ),
                ),
            ],
            options={
                "ordering": ["lesson__order"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("learner", "lesson"),
                        name="unique_learner_lesson_progress",
                    ),
                ],
            },
        ),
    ]
