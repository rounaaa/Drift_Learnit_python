import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("videos", "0004_upload_video_files"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ModerationFlag",
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
                ("label", models.CharField(max_length=50, verbose_name="Étiquette")),
                ("confidence", models.FloatField(verbose_name="Confiance")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "En attente"),
                            ("APPROVED", "Approuvé"),
                            ("REJECTED", "Rejeté"),
                        ],
                        default="PENDING",
                        max_length=10,
                        verbose_name="Statut",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Créé le"),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="Examiné le"
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_video_flags",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Examiné par",
                    ),
                ),
                (
                    "video",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="moderation_flags",
                        to="videos.video",
                        verbose_name="Vidéo",
                    ),
                ),
            ],
            options={
                "verbose_name": "Signalement de modération",
                "verbose_name_plural": "Signalements de modération",
                "ordering": ["-created_at"],
            },
        ),
    ]
