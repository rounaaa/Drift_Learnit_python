from django.core.validators import FileExtensionValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("videos", "0003_video_category_management"),
    ]

    operations = [
        migrations.RenameField(
            model_name="video",
            old_name="video_url",
            new_name="video_file",
        ),
        migrations.AlterField(
            model_name="video",
            name="video_file",
            field=models.FileField(
                upload_to="videos/",
                validators=[
                    FileExtensionValidator(
                        allowed_extensions=["mp4", "webm", "ogg", "mov"]
                    )
                ],
                verbose_name="Fichier vidéo",
            ),
        ),
    ]
