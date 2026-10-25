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
