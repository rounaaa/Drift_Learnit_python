# Modération locale des vidéos

La modération repose sur un pipeline scikit-learn TF-IDF et LogisticRegression.
Le modèle est entraîné localement avec `python manage.py train_moderation_model` ;
aucune clé ni API externe n'est utilisée. Le seuil peut être configuré avec le
paramètre Django `MODERATION_FLAG_THRESHOLD` (0,6 par défaut).

`data/moderation_dataset.csv` est un jeu de données **synthétique**, généré par
`python -m videos.ai.generate_dataset`. Il contient 300 exemples français et
anglais équilibrés entre les étiquettes `OK` et `FLAGGED`. Les exemples
`FLAGGED` couvrent six catégories : insultes, haine et discrimination, spam et
publicité, arnaques et phishing, hors-sujet (notamment casino, paris et
rencontres), et contenu adulte ou violence gratuite. Le modèle reste binaire :
il signale le texte, sans attribuer une catégorie de motif.

Le pipeline ajoute également des indicateurs textuels pour les MAJUSCULES
excessives, la ponctuation répétée et la présence d'un lien. Il analyse toujours
uniquement le texte fourni (titre et description), sans inspection de la vidéo.
Le corpus est destiné au développement et ne remplace pas une validation humaine
ou un corpus représentatif avant un usage en production.

Le modèle entraîné est enregistré dans `videos/ai/models/` et les rapports dans
`videos/ai/reports/`. Ces fichiers sont des artefacts locaux générés par les
commandes.

## Installation et lancement du module vidéo

Exécutez les commandes depuis la racine du projet (le dossier contenant
`manage.py`). Avec `uv`, installez toutes les dépendances du projet, y compris
Gemini, Celery et la génération PDF :

```powershell
uv sync
Copy-Item .env.example .env  # à faire une seule fois
```

Ajoutez ensuite votre clé dans `.env` :

```dotenv
GEMINI_API_KEY=votre_cle_gemini
```

Installez `ffmpeg` et `ffprobe` et vérifiez qu'ils sont disponibles dans un
nouveau terminal. Sous Windows :

```powershell
winget install Gyan.FFmpeg
ffmpeg -version
ffprobe -version
```

Appliquez les migrations et démarrez le serveur Django :

```powershell
uv run python manage.py migrate
uv run python manage.py runserver
```

Par défaut, `CELERY_TASK_ALWAYS_EAGER=True` exécute les tâches de génération
dans le processus Django, ce qui convient aux tests et aux démonstrations sans
Redis ni worker séparé. Pour tester le module :

```powershell
uv run python manage.py test videos
```

Pour exécuter les tâches en arrière-plan, démarrez Redis, configurez dans `.env`
`CELERY_TASK_ALWAYS_EAGER=False` et `CELERY_BROKER_URL=redis://localhost:6379/0`,
puis lancez un worker dans un second terminal :

```powershell
uv run celery -A config worker --loglevel=info
```
