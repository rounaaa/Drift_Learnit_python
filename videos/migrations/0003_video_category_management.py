from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def prepare_legacy_rows(apps, schema_editor):
    Video = apps.get_model("videos", "Video")
    Category = apps.get_model("videos", "Category")

    if Video.objects.exists():
        raise RuntimeError(
            "Existing videos have no creator or category data. Assign those values "
            "to every video before applying the video-management migration."
        )

    now = django.utils.timezone.now()
    for category in Category.objects.all():
        updates = {}
        if not category.name:
            updates["name"] = f"Catégorie migrée {category.pk}"
        if category.created_at is None:
            updates["created_at"] = now
        if updates:
            Category.objects.filter(pk=category.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("videos", "0002_alter_video_options_video_title"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="category",
            name="description",
            field=models.TextField(blank=True, default="", verbose_name="Description"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="category",
            name="created_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(prepare_legacy_rows, migrations.RunPython.noop),
        migrations.AddField(
            model_name="video",
            name="description",
            field=models.TextField(default="", verbose_name="Description"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="video",
            name="video_url",
            field=models.URLField(default="https://example.com/", verbose_name="URL de la vidéo"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="video",
            name="thumbnail_url",
            field=models.URLField(
                blank=True, default="", verbose_name="URL de la miniature"
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="video",
            name="duration_seconds",
            field=models.PositiveIntegerField(default=1, verbose_name="Durée (secondes)"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="video",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Brouillon"),
                    ("PUBLISHED", "Publié"),
                    ("ARCHIVED", "Archivé"),
                ],
                default="DRAFT",
                max_length=20,
                verbose_name="Statut",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="creator",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="videos",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="category",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="videos",
                to="videos.category",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="created_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="video",
            name="updated_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="video",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="category",
            name="name",
            field=models.CharField(max_length=100, unique=True, verbose_name="Nom"),
        ),
        migrations.AlterField(
            model_name="category",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="video",
            name="title",
            field=models.CharField(max_length=200, verbose_name="Titre"),
        ),
        migrations.AlterField(
            model_name="video",
            name="creator",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="videos",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Créateur",
            ),
        ),
        migrations.AlterField(
            model_name="video",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="videos",
                to="videos.category",
                verbose_name="Catégorie",
            ),
        ),
        migrations.AlterField(
            model_name="video",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="video",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterModelOptions(
            name="video",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Vidéo",
                "verbose_name_plural": "Vidéos",
            },
        ),
        migrations.AlterModelOptions(
            name="category",
            options={
                "ordering": ["name"],
                "verbose_name": "Catégorie",
                "verbose_name_plural": "Catégories",
            },
        ),
    ]
