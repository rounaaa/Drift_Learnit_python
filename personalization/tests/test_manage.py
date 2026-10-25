"""Tests des CRUD : US36 (recherches sauvegardées), US37 (listes), US38 (synonymes), US39 (statistiques)."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from personalization.models import SavedSearch, SearchHistory, SearchSynonym, Watchlist, WatchlistItem
from personalization.services.saved_searches import new_results_count
from personalization.services.search import default_ordering

from .base import INFO, BaseSearchTestCase


def url(name, *args):
    return reverse(f"personalization:{name}", args=args)


# ==========================================================================
# US36 — Recherches sauvegardées
# ==========================================================================
class SavedSearchCrudTests(BaseSearchTestCase):
    def setUp(self):
        self.client.force_login(self.learner)

    def create(self, **data):
        payload = {"name": "Mes cours Django", "query": "django", "content_type": "course",
                   "level": "", "ordering": "-published_at", "notify": "on"}
        payload.update(data)
        return self.client.post(url("saved-create"), payload)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(url("saved-list")).status_code, 302)

    def test_create(self):
        response = self.create(categories=[INFO])
        self.assertRedirects(response, url("saved-list"))
        saved = SavedSearch.objects.get(user=self.learner)
        self.assertEqual((saved.name, saved.query, saved.content_type), ("Mes cours Django", "django", "course"))
        self.assertEqual(saved.categories, [INFO])

    def test_create_from_search_page_returns_to_it(self):
        response = self.create(next=f"{url('search')}?q=django")
        self.assertRedirects(response, f"{url('search')}?q=django")

    def test_external_next_is_ignored(self):
        response = self.create(next="https://site-malveillant.example/")
        self.assertRedirects(response, url("saved-list"))

    def test_create_form_is_prefilled_from_search(self):
        response = self.client.get(url("saved-create"), {"q": "pandas", "type": "video"})
        form = response.context["form"]
        self.assertEqual(form.initial["query"], "pandas")
        self.assertEqual(form.initial["content_type"], "video")

    def test_name_must_be_unique_per_user(self):
        self.create()
        response = self.create(name="  mes cours   django ")
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "name", "Vous avez déjà une recherche sauvegardée avec ce nom.")
        # Un autre utilisateur peut utiliser le même nom.
        self.client.force_login(self.other)
        self.assertEqual(self.create().status_code, 302)

    def test_limit_per_user(self):
        for i in range(SavedSearch.MAX_PER_USER):
            SavedSearch.objects.create(user=self.learner, name=f"R{i}")
        response = self.create()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SavedSearch.objects.filter(user=self.learner).count(), SavedSearch.MAX_PER_USER)

    def test_list_shows_new_results(self):
        saved = SavedSearch.objects.create(user=self.learner, name="Django", query="django",
                                           last_viewed_at=timezone.now() - timedelta(days=4))
        response = self.client.get(url("saved-list"))
        row = response.context["rows"][0]
        self.assertEqual(row["saved"], saved)
        self.assertEqual(row["new_count"], 1)  # Django débutant, publié il y a 3 jours
        self.assertEqual(row["total"], 3)      # 2 cours + 1 vidéo
        self.assertContains(response, "1 nouveau contenu")

    def test_open_resets_new_results_and_redirects(self):
        saved = SavedSearch.objects.create(user=self.learner, name="Django", query="django", level="BEGINNER",
                                           categories=[INFO], last_viewed_at=timezone.now() - timedelta(days=30))
        response = self.client.get(url("saved-open", saved.pk))
        expected = f"{url('search')}?q=django&category={INFO}&level=BEGINNER"
        if default_ordering("django") != "-published_at":
            # US40 : avec l'IA, le tri par défaut d'une recherche avec mots-clés est la pertinence ;
            # le tri par date choisi à la sauvegarde est donc gardé dans le lien.
            expected += "&ordering=-published_at"
        self.assertRedirects(response, expected, fetch_redirect_response=False)
        saved.refresh_from_db()
        self.assertEqual(new_results_count(saved), 0)

    def test_edit(self):
        saved = SavedSearch.objects.create(user=self.learner, name="Ancien nom", query="django")
        response = self.client.post(url("saved-edit", saved.pk), {
            "name": "Nouveau nom", "query": "pandas", "content_type": "all", "level": "", "ordering": "title",
        })
        self.assertRedirects(response, url("saved-list"))
        saved.refresh_from_db()
        self.assertEqual((saved.name, saved.query, saved.ordering, saved.notify), ("Nouveau nom", "pandas", "title", False))

    def test_delete_with_confirmation(self):
        saved = SavedSearch.objects.create(user=self.learner, name="À supprimer")
        self.assertContains(self.client.get(url("saved-delete", saved.pk)), "Cette action est définitive")
        self.assertTrue(SavedSearch.objects.filter(pk=saved.pk).exists())  # le GET ne supprime rien
        self.assertRedirects(self.client.post(url("saved-delete", saved.pk)), url("saved-list"))
        self.assertFalse(SavedSearch.objects.filter(pk=saved.pk).exists())

    def test_toggle_notify(self):
        saved = SavedSearch.objects.create(user=self.learner, name="Alerte", notify=True)
        self.client.post(url("saved-toggle-notify", saved.pk))
        saved.refresh_from_db()
        self.assertFalse(saved.notify)

    def test_cannot_touch_someone_else_saved_search(self):
        saved = SavedSearch.objects.create(user=self.other, name="Privée")
        for name in ("saved-open", "saved-edit", "saved-delete"):
            self.assertEqual(self.client.get(url(name, saved.pk)).status_code, 404, name)
        self.assertEqual(self.client.post(url("saved-delete", saved.pk)).status_code, 404)
        self.assertTrue(SavedSearch.objects.filter(pk=saved.pk).exists())

    def test_search_page_knows_when_search_is_saved(self):
        self.create(name="Cours django", content_type="all")
        response = self.client.get(url("search"), {"q": "django"})
        self.assertEqual(response.context["matching_saved"].name, "Cours django")
        self.assertContains(response, "Recherche sauvegardée sous")

    def test_nav_badge_counts_new_results(self):
        SavedSearch.objects.create(user=self.learner, name="Django", query="django",
                                   last_viewed_at=timezone.now() - timedelta(days=4))
        response = self.client.get(url("search"))
        self.assertContains(response, '<span class="ps-badge"')


# ==========================================================================
# US37 — Listes « À regarder plus tard »
# ==========================================================================
class WatchlistCrudTests(BaseSearchTestCase):
    def setUp(self):
        self.client.force_login(self.learner)
        self.watchlist = Watchlist.objects.create(user=self.learner, name="Révisions")

    def add(self, kind, obj, **data):
        payload = {"kind": kind, "content_id": obj.pk, "watchlist": self.watchlist.pk}
        payload.update(data)
        return self.client.post(url("watchlist-item-add"), payload)

    def items(self, watchlist=None):
        return [str(i.content) for i in (watchlist or self.watchlist).items.all()]

    def test_create_list(self):
        response = self.client.post(url("watchlist-create"), {"name": "Examen de janvier", "description": "À revoir"})
        watchlist = Watchlist.objects.get(name="Examen de janvier")
        self.assertRedirects(response, url("watchlist-detail", watchlist.pk))
        self.assertEqual(watchlist.user, self.learner)

    def test_list_name_unique_per_user(self):
        response = self.client.post(url("watchlist-create"), {"name": "révisions"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Watchlist.objects.filter(user=self.learner).count(), 1)

    def test_read_lists_with_counts(self):
        self.add("video", self.v_intro)
        response = self.client.get(url("watchlist-list"))
        self.assertEqual(response.context["watchlists"][0].item_count, 1)

    def test_rename_list(self):
        self.client.post(url("watchlist-edit", self.watchlist.pk), {"name": "Révisions finales", "description": ""})
        self.watchlist.refresh_from_db()
        self.assertEqual(self.watchlist.name, "Révisions finales")

    def test_delete_list_keeps_contents(self):
        self.add("video", self.v_intro)
        self.assertRedirects(self.client.post(url("watchlist-delete", self.watchlist.pk)), url("watchlist-list"))
        self.assertFalse(Watchlist.objects.filter(pk=self.watchlist.pk).exists())
        self.assertFalse(WatchlistItem.objects.exists())
        self.v_intro.refresh_from_db()  # la vidéo existe toujours

    def test_add_video_and_course_in_order(self):
        self.add("video", self.v_intro)
        self.add("course", self.c_ml)
        self.assertEqual(self.items(), ["Introduction à Django", "Machine learning"])

    def test_add_redirects_back(self):
        response = self.add("video", self.v_intro, next=f"{url('search')}?q=django")
        self.assertRedirects(response, f"{url('search')}?q=django")

    def test_cannot_add_twice(self):
        self.add("video", self.v_intro)
        response = self.add("video", self.v_intro, next=url("search"))
        self.assertEqual(WatchlistItem.objects.count(), 1)
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any("déjà dans la liste" in m for m in messages))

    def test_cannot_add_unpublished_content(self):
        self.add("course", self.c_draft)
        self.add("course", self.c_archived)
        self.add("video", type("Missing", (), {"pk": 999999})())
        self.assertEqual(WatchlistItem.objects.count(), 0)

    def test_add_to_new_list(self):
        self.client.post(url("watchlist-item-add"), {"kind": "video", "content_id": self.v_pandas.pk,
                                                    "new_list": "Data"})
        watchlist = Watchlist.objects.get(user=self.learner, name="Data")
        self.assertEqual(self.items(watchlist), ["Pandas pour l'analyse de données"])

    def test_move_items(self):
        for course in (self.c_django, self.c_ml, self.c_english):
            self.add("course", course)
        item = self.watchlist.items.get(course=self.c_english)
        self.client.post(url("watchlist-item-move", item.pk, "up"))
        self.assertEqual(self.items(), ["Django débutant", "Anglais professionnel", "Machine learning"])
        self.client.post(url("watchlist-item-move", item.pk, "up"))
        self.client.post(url("watchlist-item-move", item.pk, "up"))  # déjà en haut : rien ne change
        self.assertEqual(self.items(), ["Anglais professionnel", "Django débutant", "Machine learning"])
        self.client.post(url("watchlist-item-move", item.pk, "down"))
        self.assertEqual(self.items(), ["Django débutant", "Anglais professionnel", "Machine learning"])

    def test_note_and_remove(self):
        self.add("video", self.v_intro)
        item = self.watchlist.items.get()
        self.client.post(url("watchlist-item-note", item.pk), {f"item{item.pk}-note": "Revoir le chapitre 2"})
        item.refresh_from_db()
        self.assertEqual(item.note, "Revoir le chapitre 2")
        self.client.post(url("watchlist-item-remove", item.pk))
        self.assertEqual(self.items(), [])

    def test_search_page_shows_saved_state(self):
        self.add("video", self.v_intro)
        response = self.client.get(url("search"), {"q": "django"})
        self.assertIn(("video", self.v_intro.pk), response.context["saved_keys"])
        self.assertContains(response, "Dans vos listes")

    def test_privacy(self):
        other_list = Watchlist.objects.create(user=self.other, name="Privée")
        item = WatchlistItem.objects.create(watchlist=other_list, video=self.v_intro, position=1)
        self.assertEqual(self.client.get(url("watchlist-detail", other_list.pk)).status_code, 404)
        self.assertEqual(self.client.post(url("watchlist-delete", other_list.pk)).status_code, 404)
        self.assertEqual(self.client.post(url("watchlist-item-remove", item.pk)).status_code, 404)
        self.add("course", self.c_ml, watchlist=other_list.pk)
        self.assertEqual(other_list.items.count(), 1)

    def test_actions_require_post(self):
        self.add("video", self.v_intro)
        item = self.watchlist.items.get()
        self.assertEqual(self.client.get(url("watchlist-item-remove", item.pk)).status_code, 405)
        self.assertEqual(self.client.get(url("watchlist-item-add")).status_code, 405)


# ==========================================================================
# US38 — Synonymes (administrateur)
# ==========================================================================
class SynonymCrudTests(BaseSearchTestCase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_only_admins(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(url("synonym-list")).status_code, 403)
        self.assertEqual(self.client.post(url("synonym-create"), {"term": "x", "synonyms": "y"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url("synonym-list")).status_code, 302)

    def test_admin_role_staff_and_superuser_are_admins(self):
        # self.admin a le rôle ADMIN de LearnIt (sans is_staff)
        self.assertEqual(self.client.get(url("synonym-list")).status_code, 200)
        self.other.is_staff = True
        self.other.save()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url("synonym-list")).status_code, 200)
        self.creator.is_superuser = True
        self.creator.save()
        self.client.force_login(self.creator)
        self.assertEqual(self.client.get(url("synonym-list")).status_code, 200)

    def test_creator_is_not_admin(self):
        self.client.force_login(self.creator)
        self.assertEqual(self.client.get(url("stats")).status_code, 403)

    def test_create(self):
        response = self.client.post(url("synonym-create"), {
            "term": " BDD ", "synonyms": "Base de données, SQL", "bidirectional": "on", "is_active": "on"})
        self.assertRedirects(response, url("synonym-list"))
        synonym = SearchSynonym.objects.get()
        self.assertEqual((synonym.term, synonym.synonyms, synonym.created_by), ("bdd", "base de données, sql", self.admin))

    def test_create_prefilled_from_stats(self):
        response = self.client.get(url("synonym-create"), {"term": "kubernetes"})
        self.assertEqual(response.context["form"].initial["term"], "kubernetes")

    def test_validation(self):
        SearchSynonym.objects.create(term="ml", synonyms="machine learning")
        duplicate = self.client.post(url("synonym-create"), {"term": "ML", "synonyms": "ia"})
        self.assertFormError(duplicate.context["form"], "term",
                             "Le terme « ml » existe déjà. Modifiez-le plutôt que d'en créer un second.")
        same = self.client.post(url("synonym-create"), {"term": "web", "synonyms": "web, "})
        self.assertFormError(same.context["form"], "synonyms", "Ajoutez au moins un synonyme différent du terme.")

    def test_list_filter_and_tester(self):
        SearchSynonym.objects.create(term="ml", synonyms="machine learning")
        SearchSynonym.objects.create(term="bdd", synonyms="sql")
        response = self.client.get(url("synonym-list"), {"q": "machine", "tester": "ml"})
        self.assertEqual([s.term for s in response.context["page"]], ["ml"])
        self.assertEqual(response.context["test"]["with_synonyms"], 1)
        self.assertEqual(response.context["test"]["without"], 0)

    def test_edit_toggle_delete(self):
        synonym = SearchSynonym.objects.create(term="ml", synonyms="machine learning")
        self.client.post(url("synonym-edit", synonym.pk), {"term": "ml", "synonyms": "apprentissage automatique",
                                                          "is_active": "on"})
        synonym.refresh_from_db()
        self.assertEqual((synonym.synonyms, synonym.bidirectional), ("apprentissage automatique", False))

        self.client.post(url("synonym-toggle", synonym.pk))
        synonym.refresh_from_db()
        self.assertFalse(synonym.is_active)

        self.assertContains(self.client.get(url("synonym-delete", synonym.pk)), "Cette action est définitive")
        self.client.post(url("synonym-delete", synonym.pk))
        self.assertFalse(SearchSynonym.objects.exists())

    def test_search_page_shows_synonyms_used(self):
        SearchSynonym.objects.create(term="ml", synonyms="machine learning")
        response = self.client.get(url("search"), {"q": "ml"})
        self.assertEqual(self.page_titles(response), ["Machine learning"])
        self.assertContains(response, "Inclut aussi")
        self.assertContains(response, "<mark>Machine learning</mark>")


# ==========================================================================
# US39 — Statistiques (administrateur)
# ==========================================================================
class StatsTests(BaseSearchTestCase):
    def setUp(self):
        self.client.force_login(self.admin)
        now = timezone.now()
        for query, results, days_ago, user in [
            ("django", 4, 0, self.learner), ("Django", 4, 1, self.other), ("kubernetes", 0, 2, self.learner),
            ("kubernetes", 0, 3, self.other), ("pandas", 1, 40, self.learner),
        ]:
            entry = SearchHistory.objects.create(user=user, query=query, results_count=results)
            SearchHistory.objects.filter(pk=entry.pk).update(created_at=now - timedelta(days=days_ago))

    def test_only_admins(self):
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(url("stats")).status_code, 403)
        self.assertEqual(self.client.get(url("stats-export")).status_code, 403)

    def test_overview_on_30_days(self):
        response = self.client.get(url("stats"))
        overview = response.context["overview"]
        self.assertEqual((overview["total"], overview["users"], overview["zero"], overview["zero_rate"]), (4, 2, 2, 50))

    def test_period_filter(self):
        self.assertEqual(self.client.get(url("stats"), {"periode": 90}).context["overview"]["total"], 5)
        self.assertEqual(self.client.get(url("stats"), {"periode": "abc"}).context["days"], 30)

    def test_top_and_zero_result_queries(self):
        response = self.client.get(url("stats"))
        self.assertEqual([(r["query"], r["count"]) for r in response.context["top"]], [("django", 2), ("kubernetes", 2)])
        self.assertEqual([r["query"] for r in response.context["zero"]], ["kubernetes"])
        self.assertContains(response, f'{url("synonym-create")}?term=kubernetes')

    def test_series_has_one_entry_per_day(self):
        series = self.client.get(url("stats"), {"periode": 7}).context["series"]
        self.assertEqual(len(series), 7)
        self.assertEqual(sum(d["count"] for d in series), 4)

    def test_csv_export(self):
        response = self.client.get(url("stats-export"), {"periode": 30})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        lines = response.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(lines[0], "date;utilisateur;recherche;nombre_de_resultats")
        self.assertEqual(len(lines), 5)
