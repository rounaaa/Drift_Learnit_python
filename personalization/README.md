# Module 6 — Recherche et personnalisation (LearnIt)

Responsable : Yomna. App Django `personalization`, adaptée au projet LearnIt de l'équipe.

| US | Fonctionnalité | Page |
| --- | --- | --- |
| US31 | Recherche par mot-clé dans les vidéos et les cours | `/recherche/` |
| US32 | Filtres par catégorie et par niveau | `/recherche/` |
| US33 | Tri par date de publication | `/recherche/` |
| US34 | Centres d'intérêt | `/recherche/centres-interet/` |
| US35 | Recommandations | `/recherche/pour-vous/` |
| US36 | Recherches sauvegardées + alerte de nouveaux contenus (CRUD) | `/recherche/sauvegardees/` |
| US37 | Listes « À regarder plus tard » (CRUD) | `/recherche/listes/` |
| US38 | Synonymes de recherche (CRUD, administrateur) | `/recherche/gestion/synonymes/` |
| US39 | Statistiques des recherches + export CSV (administrateur) | `/recherche/gestion/statistiques/` |

113 tests automatiques (1 en attente du module Progression, voir plus bas).

---

## Ce qui est adapté au projet de l'équipe

| Élément de l'équipe | Ce que fait le module |
| --- | --- |
| `users.User` (rôles LEARNER, CREATOR, ADMIN) | Utilisé tel quel. La gestion (US38, US39) est ouverte au rôle ADMIN, aux `is_staff` et aux superutilisateurs |
| `courses.Course.category` (codes INFORMATIQUE, MATHEMATIQUES, LANGUES…) | Ce sont **les catégories du module** : filtres, centres d'intérêt, recommandations |
| `courses.Course` / `Enrollment` | Recherche, filtres par niveau, recommandations ; les cours où l'apprenant est inscrit ne sont pas recommandés |
| URL `course_detail` | Les titres des cours renvoient vers la page de détail du module Cours |
| `videos.Video` (pour l'instant : un titre seulement) | Cherché par titre. Statut, date, description et catégorie seront pris en compte **automatiquement** dès qu'ils existeront |
| `progress.LearningHistory` (vide pour l'instant) | Ignorée tant qu'elle n'a pas ses champs `user` et `video`, puis utilisée automatiquement par les recommandations |
| `templates/base.html` | Les pages du module l'étendent : même en-tête, mêmes messages, même pied de page, mêmes boutons et badges |
| Placeholder `personalization` (UserPreference, SearchHistory, Recommendation vides) | Remplacé par le vrai module. La migration `0001` de l'équipe est **gardée telle quelle** ; `0002` crée les vraies tables |

Aucun réglage n'est à ajouter dans `settings.py` (l'app `personalization` y est déjà).

---

## Intégrer dans le dépôt sans conflit Git

Seuls **2 endroits** du dépôt changent : le dossier `personalization/` (le tien) et **une ligne** de `config/urls.py`.

### 1. Mettre ta branche à jour

Dans GitHub Desktop : **Fetch origin** → **Pull origin**, puis **Current branch → New branch** → `module-recherche`.

### 2. Remplacer le dossier `personalization/`

*Repository → Show in Explorer*, puis :

1. Supprime **tout** le dossier `personalization/` du dépôt (c'est le placeholder vide de l'équipe).
2. Colle à sa place le dossier `personalization/` de ce zip.

Le fichier `personalization/migrations/0001_initial.py` est identique à celui de l'équipe : Git ne le verra pas comme modifié.

### 3. Ajouter une ligne dans `config/urls.py`

```python
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('courses.urls')),
    path('', include('users.urls')),
    path('', include('django.contrib.auth.urls')),
    path('recherche/', include('personalization.urls')),   # ← ajouter cette ligne
]
```

### 4. Migrer et tester

```bash
python manage.py migrate
python manage.py test personalization
```

Résultat attendu : `Ran 113 tests ... OK (skipped=1)`.

Si `migrate` ou `test` dit qu'il manque une migration pour **users** (`0004_alter_user_role`) : c'est dans le module Utilisateurs (le libellé « Créateur » est devenu « Formateur » sans migration). Préviens son responsable ; ne la crée pas dans ta branche, sinon elle sera en conflit avec la sienne.

### 5. Données de démonstration (facultatif)

```bash
python manage.py seed_personalization_demo
python manage.py runserver
```

Ouvre http://127.0.0.1:8000/recherche/ et connecte-toi avec `learner_user` (apprenant) ou `admin_user` (gestion), mot de passe `LearnIt2026!`. La commande n'efface rien ; elle ne crée ces comptes que s'ils n'existent pas.

### 6. Commit, push, Pull Request

Dans GitHub Desktop, vérifie que la liste ne contient que `personalization/…` et `config/urls.py`, puis :

- **Summary** : `Module Recherche et personnalisation (US31-US39)`
- **Commit to module-recherche** → **Publish branch** → **Create Pull Request**

---

## À proposer aux autres membres (ne pas le faire dans ta branche)

| Membre | Demande | Pourquoi |
| --- | --- | --- |
| Responsable de `base.html` | Ajouter `<li><a href="{% url 'personalization:search' %}" class="nav-link">🔍 Rechercher</a></li>` dans les menus | Lien vers le module depuis l'en-tête |
| Membre 1 (Vidéos) | Ajouter à `Video` : `description`, `status` (DRAFT / PUBLISHED / ARCHIVED), `published_at`, et `category = models.CharField(max_length=50, choices=Course.Category.choices)` | Les vidéos seront filtrées, triées et recommandées comme les cours, sans rien changer à ce module |
| Jawher (Progression) | Ajouter à `LearningHistory` : `user` (FK User) et `video` (FK Video) | Active les recommandations basées sur l'historique (et le test aujourd'hui en attente) |
| Responsable Utilisateurs | Créer la migration `users/0004` (libellé « Formateur ») | Supprime l'avertissement de migration manquante |

---

## Structure du dossier

```
personalization/
├── README.md                    # ce fichier
├── conf.py                      # lecture des modèles de l'équipe (champs optionnels, catégories)
├── models.py                    # UserPreference, SearchHistory, Recommendation,
│                                # SavedSearch, Watchlist, WatchlistItem, SearchSynonym
├── migrations/
│   ├── 0001_initial.py          # celle de l'équipe, inchangée
│   └── 0002_module_recherche_personnalisation.py
├── forms.py, permissions.py, utils.py
├── services/                    # logique métier : search, synonyms, recommendations,
│                                # saved_searches, watchlists, stats
├── web_views.py                 # recherche, centres d'intérêt, Pour vous
├── views_saved.py               # US36 (CRUD)
├── views_watchlists.py          # US37 (CRUD)
├── views_admin.py               # US38 (CRUD) + US39
├── urls.py                      # toutes les routes /recherche/...
├── templates/personalization/   # pages (étendent base.html de l'équipe)
├── static/personalization/personalization.css   # classes préfixées ps- : aucun effet hors du module
├── templatetags/personalization_tags.py
├── admin.py                     # les 7 tables dans /admin/
├── management/commands/
│   ├── refresh_recommendations.py
│   └── seed_personalization_demo.py
└── tests/                       # 113 tests
```

## Limites connues

- La recherche utilise `icontains` : pas de tolérance aux fautes de frappe. Les synonymes couvrent les cas fréquents.
- Les recherches des visiteurs non connectés ne sont pas enregistrées, donc absentes des statistiques.
