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
| US40 | **Recherche intelligente (IA)** : pertinence, fautes de frappe, « Vouliez-vous dire », contenus similaires | `/recherche/`, `/recherche/similaires/…` |

147 tests automatiques (1 en attente du module Progression, voir plus bas).

---

## US40 — Recherche intelligente (IA)

> *En tant qu'apprenant, je veux des résultats classés par pertinence, qui tolèrent mes fautes de frappe, et voir des contenus similaires à celui qui m'intéresse.*

Machine learning **local** avec scikit-learn : gratuit, sans clé d'API, fonctionne hors ligne.

| Fonction | Comment ça marche | Exemple |
| --- | --- | --- |
| Tri par pertinence | Chaque contenu devient un vecteur **TF-IDF** (titre ×3, description, catégorie, niveau). Les résultats sont classés par **similarité cosinus** avec la requête. C'est le tri par défaut dès qu'il y a des mots-clés. | « django » : les contenus avec Django dans le titre passent avant ceux qui le citent dans la description |
| Fautes de frappe et accents | Un 2ᵉ TF-IDF sur des **groupes de 3 à 5 lettres** ; accents ignorés. Utilisé quand la recherche exacte ne trouve rien. | « djnago » → cours Django ; « securite » → « sécurité » |
| Vouliez-vous dire… ? | Chaque mot inconnu est remplacé par le mot connu le plus proche (difflib) | « machine lerning » → *machine learning* |
| Contenus similaires | Similarité cosinus entre contenus. Lien « ≈ Contenus similaires » sous chaque résultat. | `/recherche/similaires/course/3/` |
| Recommandations (raison SIMILAR) | Profil de l'apprenant = contenus de ses listes + vidéos regardées + 10 dernières recherches. Les contenus proches de ce profil gagnent jusqu'à +2,5 points. | A enregistré « Django débutant » → « Django avancé » recommandé |
| Gestion (admin) | Bloc « Moteur de recherche IA » : état de l'index, bouton « Reconstruire ». Pour chaque recherche sans résultat, la correction proposée par l'IA (et le lien pour en faire un synonyme). | `/recherche/gestion/statistiques/` |

**Installation :** `pip install scikit-learn` (à ajouter au `requirements.txt` de l'équipe : voir plus bas).

**scikit-learn est facultatif :** sans lui, le module fonctionne exactement comme avant (recherche par mots-clés, tri par date, recommandations par règles, « contenus similaires » = même catégorie). Les 29 tests IA sont alors ignorés.

L'index est gardé en mémoire et se reconstruit tout seul quand un contenu est ajouté, publié ou modifié (et au plus tard toutes les 10 minutes). Rien n'est stocké en base, à part la nouvelle raison de recommandation (migration `0003`).

Les statistiques gardent le nombre de résultats **exacts** : une recherche avec faute (« djnago ») reste comptée « sans résultat », pour que l'administrateur la voie.

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

Résultat attendu : `Ran 147 tests ... OK (skipped=1)` (ou `skipped=30` si scikit-learn n'est pas installé).

Si `migrate` ou `test` dit qu'il manque une migration pour **users** (`0004_alter_user_role`) : c'est dans le module Utilisateurs (le libellé « Créateur » est devenu « Formateur » sans migration). Préviens son responsable ; ne la crée pas dans ta branche, sinon elle sera en conflit avec la sienne.

### 5. Données de démonstration (facultatif)

```bash
python manage.py seed_personalization_demo
python manage.py runserver
```

Ouvre http://127.0.0.1:8000/recherche/ et connecte-toi avec `learner_user` (apprenant) ou `admin_user` (gestion), mot de passe `LearnIt2026!`. La commande n'efface rien ; elle ne crée ces comptes que s'ils n'existent pas.

### 6. Commit, push, Pull Request

Dans GitHub Desktop, vérifie que la liste ne contient que `personalization/…` et `config/urls.py`, puis :

- **Summary** : `Module Recherche et personnalisation (US31-US40)`
- **Commit to module-recherche** → **Publish branch** → **Create Pull Request**

---

## À proposer aux autres membres (ne pas le faire dans ta branche)

| Membre | Demande | Pourquoi |
| --- | --- | --- |
| Responsable de `base.html` | Ajouter `<li><a href="{% url 'personalization:search' %}" class="nav-link">🔍 Rechercher</a></li>` dans les menus | Lien vers le module depuis l'en-tête |
| Membre 1 (Vidéos) | Ajouter à `Video` : `description`, `status` (DRAFT / PUBLISHED / ARCHIVED), `published_at`, et `category = models.CharField(max_length=50, choices=Course.Category.choices)` | Les vidéos seront filtrées, triées et recommandées comme les cours, sans rien changer à ce module |
| Jawher (Progression) | Ajouter à `LearningHistory` : `user` (FK User) et `video` (FK Video) | Active les recommandations basées sur l'historique (et le test aujourd'hui en attente) |
| Responsable Utilisateurs | Créer la migration `users/0004` (libellé « Formateur ») | Supprime l'avertissement de migration manquante |
| Responsable de `requirements.txt` | Ajouter la ligne `scikit-learn>=1.4` | Active l'US40 (recherche intelligente) chez tout le monde |

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
│   ├── 0002_module_recherche_personnalisation.py
│   └── 0003_recherche_intelligente.py   # US40 : raison de recommandation SIMILAR
├── forms.py, permissions.py, utils.py
├── services/                    # logique métier : search, synonyms, recommendations,
│                                # saved_searches, watchlists, stats,
│                                # ai (US40 : TF-IDF, similarité cosinus)
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
└── tests/                       # 147 tests (dont test_ai.py : US40)
```

## Limites connues

- La recherche exacte utilise `icontains` ; la tolérance aux fautes (US40) ne s'active que si elle ne trouve rien.
- L'IA compare des mots, pas le sens : « voiture » et « automobile » ne sont reliés que par un synonyme (US38).
- Tant que les vidéos n'ont qu'un titre, l'IA les compare sur leur titre seulement.
- Les recherches des visiteurs non connectés ne sont pas enregistrées, donc absentes des statistiques.
