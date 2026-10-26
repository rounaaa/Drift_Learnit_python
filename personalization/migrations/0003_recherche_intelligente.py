# US40 — Recherche intelligente : nouvelle raison de recommandation SIMILAR (IA)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personalization", "0002_module_recherche_personnalisation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="recommendation",
            name="reason",
            field=models.CharField(
                choices=[
                    ("INTEREST", "Correspond à vos centres d'intérêt"),
                    ("SIMILAR", "Proche de vos listes et de vos recherches"),
                    ("HISTORY", "Proche de ce que vous avez regardé"),
                    ("LEVEL", "Adapté à votre niveau"),
                    ("POPULAR", "Populaire sur la plateforme"),
                    ("NEW", "Nouveauté"),
                ],
                max_length=20,
            ),
        ),
    ]
