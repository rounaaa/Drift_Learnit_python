# LearnIt

Projet Django avec structure modulaire basée sur `uv`.

## 📁 Structure du projet

```text
learnit/
├── config/             # Configuration principale Django (settings, urls, asgi, wsgi)
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── src/                # Code source du package
│   └── learnit/
│       └── __init__.py
├── templates/          # Templates HTML globaux
│   ├── base.html
│   ├── header.html
│   └── footer.html
├── static/             # Fichiers statiques (CSS, JS, images)
├── media/              # Fichiers uploadés par les utilisateurs
├── .env.example        # Modèle de variables d'environnement
├── .gitignore          # Fichiers et dossiers ignorés par git
├── manage.py           # Utilitaire de commande Django
└── pyproject.toml      # Configuration du projet et dépendances
```

## 🚀 Démarrage rapide

### 1. Avec `uv` (recommandé)

```bash
# Installer les dépendances
uv sync

# Appliquer les migrations
uv run python manage.py migrate

# Lancer le serveur
uv run python manage.py runserver
```

### 2. Avec `venv` & `pip` classique

```bash
# Créer et activer l'environnement virtuel
python -m venv .venv
# Sur Windows :
.venv\Scripts\activate

# Installer Django et dotenv
pip install django python-dotenv

# Migrer et démarrer
python manage.py migrate
python manage.py runserver
```

## ➕ Créer une nouvelle application

```bash
python manage.py startapp nom_app
```
N'oubliez pas d'ajouter `'nom_app'` dans `INSTALLED_APPS` dans [settings.py](file:///c:/Users/windows%2010/Desktop/django_prof/learnit/config/settings.py).

## Modération des vidéos

La modération locale utilise un classifieur scikit-learn. Après installation des
dépendances de développement, générez le jeu de données synthétique et entraînez
le modèle :

```bash
python -m videos.ai.generate_dataset
python manage.py train_moderation_model
python manage.py evaluate_moderation_model
python manage.py test videos
coverage run --source=videos manage.py test videos
coverage report -m
```

Installez aussi l’extra de développement avec `uv sync --group dev` pour
disposer de la commande `coverage`.

Le jeu de données est synthétique et les prédictions sont destinées à signaler
des contenus à revoir, pas à remplacer une décision humaine.

## Sous-titres traduits et résumés vidéo

Le module vidéo génère une transcription horodatée dans la langue détectée, puis
traduit à la demande les sous-titres et résumés en français, arabe ou anglais.
Les résultats terminés sont enregistrés et réutilisés pour tous les apprenants.
Sur une vidéo publiée, les boutons **Sous-titres** et **Résumé PDF** permettent
de sélectionner une langue; le PDF est produit localement. Le créateur propriétaire
et les administrateurs peuvent fournir une source, préparer le contenu avant
publication et relancer une génération. Le résumé et ses traductions sont filtrés
par le système de modération existant avant d'être servis.

Copiez `.env.example` vers `.env`, puis ajoutez une clé Gemini obtenue depuis
[Google AI Studio](https://aistudio.google.com/apikey) dans `GEMINI_API_KEY`.
Les modèles sont définis dans `videos/ai/gemini_service.py` selon la
[documentation officielle des modèles Gemini](https://ai.google.dev/gemini-api/docs/models):
`gemini-3.8-flash` pour la transcription audio avec sortie JSON structurée et
pour la traduction.

`ffmpeg` et `ffprobe` doivent être installés et accessibles via `PATH` (par
exemple avec `winget install Gyan.FFmpeg` sous Windows, `brew install ffmpeg`
sous macOS ou le gestionnaire de paquets de la distribution Linux). Les sources
acceptées sont limitées à 50 Mo et 10 minutes par défaut. Ces limites sont
configurables avec `VIDEO_SUMMARY_MAX_FILE_SIZE` et
`VIDEO_SUMMARY_MAX_DURATION_SECONDS`.

Pour une démo sans Redis, gardez `CELERY_TASK_ALWAYS_EAGER=True` (valeur par
défaut). En production, configurez Redis dans `CELERY_BROKER_URL`, mettez
`CELERY_TASK_ALWAYS_EAGER=False` et lancez un worker:

```bash
celery -A config worker --loglevel=info
```

Avec plusieurs processus web, gardez `VIDEO_AI_CACHE_URL` sur un cache Redis
partagé pour appliquer les limites de débit par utilisateur à travers tous les
workers. Si le broker Celery est Redis et le mode eager désactivé, il est
réutilisé par défaut.

Les PDF arabes embarquent la police Amiri (SIL Open Font License), et utilisent
la mise en forme RTL avec `arabic-reshaper` et `python-bidi`.
