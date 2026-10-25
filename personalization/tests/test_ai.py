"""Tests de l'US40 — Recherche intelligente (TF-IDF, scikit-learn).

Les tests marqués skipUnless(AI_AVAILABLE) ne tournent que si scikit-learn est installé.
La classe WithoutAITests vérifie que le module marche toujours sans lui.
"""
from unittest import mock, skipUnless

from django.urls import reverse

from personalization.forms import SearchForm
from personalization.models import Recommendation, SearchHistory, Watchlist, WatchlistItem
from personalization.services import ai
from personalization.services.recommendations import get_recommendations
from personalization.services.search import DEFAULT_ORDERING, RELEVANCE, SearchParams, default_ordering, search_contents

from .base import BaseSearchTestCase, make_video

SEARCH_PAGE = reverse("personalization:search")


def search(**kwargs):
    return search_contents(SearchParams(**kwargs))


def similar_url(kind, pk):
    return reverse("personalization:similar", args=[kind, pk])


@skipUnless(ai.AI_AVAILABLE, "scikit-learn n'est pas installé")
class RelevanceTests(BaseSearchTestCase):
    def test_default_ordering_is_relevance_when_there_are_keywords(self):
        form = SearchForm({"q": "django"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["ordering"], RELEVANCE)
        form = SearchForm({})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["ordering"], DEFAULT_ORDERING)

    def test_title_matches_rank_before_description_matches(self):
        # Un cours (la vidéo de l'équipe n'a pas encore de description)
        self._course("Bases de données", "Exemples avec Django en fin de cours", "INFORMATIQUE", "BEGINNER", 2)
        titles = self.titles(search(q="django", ordering=RELEVANCE))
        self.assertEqual(titles[-1], "Bases de données")
        self.assertCountEqual(titles[:3], ["Introduction à Django", "Django débutant", "Django avancé"])

    def test_two_words_prefers_contents_with_both(self):
        make_video("Sécurité réseau", "Pare-feu et VPN")
        result = search(q="django sécurité", ordering=RELEVANCE, use_synonyms=False)
        self.assertEqual(self.titles(result), ["Django avancé"])

    def test_relevance_percent_starts_at_100(self):
        result = search(q="django", ordering=RELEVANCE)
        percents = [obj.relevance_percent for _, obj in result.items]
        self.assertEqual(percents[0], 100)
        self.assertEqual(percents, sorted(percents, reverse=True))

    def test_relevance_keeps_filters_and_pagination(self):
        full = self.titles(search(q="django", ordering=RELEVANCE))
        pages = self.titles(search(q="django", ordering=RELEVANCE, page_size=2)) + \
            self.titles(search(q="django", ordering=RELEVANCE, page_size=2, page=2))
        self.assertEqual(pages, full)
        self.assertEqual(self.titles(search(q="django", ordering=RELEVANCE, content_type="video")),
                         ["Introduction à Django"])

    def test_relevance_without_keywords_falls_back_to_date(self):
        result = search(ordering=RELEVANCE, content_type="course")
        self.assertEqual(result.ordering, DEFAULT_ORDERING)
        self.assertEqual(self.titles(result)[0], "Django débutant")


@skipUnless(ai.AI_AVAILABLE, "scikit-learn n'est pas installé")
class TypoToleranceTests(BaseSearchTestCase):
    def test_typo_finds_approximate_results_and_suggestion(self):
        result = search(q="djnago", fuzzy=True)
        self.assertTrue(result.approximate)
        self.assertEqual(result.exact_count, 0)
        self.assertEqual(result.suggestion, "django")
        self.assertCountEqual(self.titles(result), ["Introduction à Django", "Django débutant", "Django avancé"])

    def test_missing_accents_are_tolerated(self):
        result = search(q="securite", fuzzy=True)
        self.assertEqual(self.titles(result), ["Django avancé"])

    def test_suggestion_restores_accents(self):
        self.assertEqual(ai.get_index().suggest("securte"), "sécurité")
        self.assertEqual(ai.get_index().suggest("djnago avancé"), "django avancé")
        self.assertIsNone(ai.get_index().suggest("django"))

    def test_approximate_results_respect_filters(self):
        result = search(q="djnago", fuzzy=True, content_type="video")
        self.assertEqual(self.titles(result), ["Introduction à Django"])

    def test_drafts_are_never_returned(self):
        titles = self.titles(search(q="brouilon", fuzzy=True))
        self.assertNotIn("Django brouillon", titles)

    def test_nonsense_query_gives_nothing(self):
        result = search(q="zzqqxx", fuzzy=True)
        self.assertEqual(result.count, 0)
        self.assertFalse(result.approximate)

    def test_fuzzy_is_off_by_default(self):
        # Recherches sauvegardées, statistiques : seulement les résultats exacts
        self.assertEqual(search(q="djnago").count, 0)

    def test_index_follows_new_contents(self):
        self.assertEqual(search(q="kubernets", fuzzy=True).count, 0)
        make_video("Kubernetes pour débuter", "Déployer des conteneurs")
        self.assertEqual(self.titles(search(q="kubernets", fuzzy=True)), ["Kubernetes pour débuter"])


@skipUnless(ai.AI_AVAILABLE, "scikit-learn n'est pas installé")
class SearchPageAITests(BaseSearchTestCase):
    def test_page_shows_suggestion_and_approximate_results(self):
        response = self.client.get(SEARCH_PAGE, {"q": "djnago"})
        self.assertContains(response, "Vouliez-vous dire")
        self.assertContains(response, "?q=django")
        self.assertContains(response, "contenus proches de « djnago »")
        self.assertEqual(len(response.context["items"]), 3)

    def test_history_keeps_zero_for_typos(self):
        self.client.force_login(self.learner)
        self.client.get(SEARCH_PAGE, {"q": "djnago"})
        self.assertEqual(SearchHistory.objects.get(user=self.learner).results_count, 0)

    def test_relevance_option_and_meter(self):
        response = self.client.get(SEARCH_PAGE, {"q": "django"})
        self.assertEqual(response.context["params"].ordering, RELEVANCE)
        self.assertContains(response, "Pertinence (IA)")
        self.assertContains(response, "Pertinence 100 %")

    def test_relevance_option_hidden_without_keywords(self):
        response = self.client.get(SEARCH_PAGE)
        self.assertNotContains(response, "Pertinence (IA)")

    def test_date_ordering_still_available(self):
        response = self.client.get(SEARCH_PAGE, {"q": "django", "ordering": "-published_at"})
        self.assertEqual(self.page_titles(response), self.titles(search(q="django", ordering="-published_at")))
        self.assertNotContains(response, "Pertinence 100 %")


@skipUnless(ai.AI_AVAILABLE, "scikit-learn n'est pas installé")
class SimilarContentTests(BaseSearchTestCase):
    def test_similar_courses_and_videos(self):
        similar = [obj.title for _, obj, _ in ai.similar_contents("course", self.c_django)]
        self.assertEqual(similar[:2], ["Django avancé", "Introduction à Django"])
        self.assertNotIn("Django débutant", similar)        # pas lui-même
        self.assertNotIn("Django brouillon", similar)       # jamais de brouillon

    def test_similar_page(self):
        response = self.client.get(similar_url("course", self.c_django.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Django avancé")
        self.assertContains(response, "Proximité 100 %")

    def test_similar_link_on_search_results(self):
        response = self.client.get(SEARCH_PAGE, {"q": "django"})
        self.assertContains(response, similar_url("course", self.c_django.pk))

    def test_unpublished_or_unknown_content_is_404(self):
        self.assertEqual(self.client.get(similar_url("course", self.c_draft.pk)).status_code, 404)
        self.assertEqual(self.client.get(similar_url("podcast", 1)).status_code, 404)


@skipUnless(ai.AI_AVAILABLE, "scikit-learn n'est pas installé")
class SimilarRecommendationTests(BaseSearchTestCase):
    def test_watchlist_contents_drive_recommendations(self):
        watchlist = Watchlist.objects.create(user=self.learner, name="À voir")
        WatchlistItem.objects.create(watchlist=watchlist, course=self.c_django)
        recos = get_recommendations(self.learner, force_refresh=True)
        self.assertEqual(recos[0].course, self.c_django_adv)
        self.assertEqual(recos[0].reason, Recommendation.Reason.SIMILAR)
        # Ce qui est déjà dans une liste n'est pas recommandé
        self.assertNotIn(self.c_django, [r.course for r in recos])

    def test_recent_searches_drive_recommendations(self):
        SearchHistory.objects.create(user=self.learner, query="pandas", results_count=1)
        top = get_recommendations(self.learner, limit=1, force_refresh=True)[0]
        self.assertEqual(top.video, self.v_pandas)
        self.assertEqual(top.reason, Recommendation.Reason.SIMILAR)

    def test_reason_is_displayed(self):
        SearchHistory.objects.create(user=self.learner, query="pandas", results_count=1)
        self.client.force_login(self.learner)
        response = self.client.get(reverse("personalization:recommendations"))
        self.assertContains(response, "Proche de vos listes et de vos recherches")


@skipUnless(ai.AI_AVAILABLE, "scikit-learn n'est pas installé")
class AIAdminTests(BaseSearchTestCase):
    def test_stats_page_shows_engine_and_typo_fix(self):
        SearchHistory.objects.create(user=self.learner, query="djnago", results_count=0)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("personalization:stats"))
        self.assertContains(response, "Moteur de recherche IA")
        self.assertContains(response, "L'IA propose « django »")
        self.assertContains(response, "synonyms=django")

    def test_rebuild_index(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("personalization:ai-rebuild"), follow=True)
        self.assertContains(response, "Index IA reconstruit : 6 contenus indexés.")

    def test_rebuild_is_admin_only_and_post_only(self):
        url = reverse("personalization:ai-rebuild")
        self.client.force_login(self.learner)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)


class WithoutAITests(BaseSearchTestCase):
    """Sans scikit-learn, tout fonctionne comme avant l'US40."""

    def setUp(self):
        patcher = mock.patch.object(ai, "AI_AVAILABLE", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_ordering_stays_by_date(self):
        self.assertEqual(default_ordering("django"), DEFAULT_ORDERING)
        form = SearchForm({"q": "django"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["ordering"], DEFAULT_ORDERING)

    def test_relevance_falls_back_to_date(self):
        result = search(q="django", ordering=RELEVANCE, content_type="course")
        self.assertEqual(result.ordering, DEFAULT_ORDERING)
        self.assertEqual(self.titles(result), ["Django débutant", "Django avancé"])

    def test_no_approximate_results(self):
        result = search(q="djnago", fuzzy=True)
        self.assertEqual((result.count, result.approximate, result.suggestion), (0, False, ""))

    def test_similar_falls_back_to_same_category(self):
        similar = [obj.title for _, obj, score in ai.similar_contents("course", self.c_django)]
        self.assertIn("Django avancé", similar)
        self.assertNotIn("Anglais professionnel", similar)
        response = self.client.get(similar_url("course", self.c_django.pk))
        self.assertContains(response, "Installez scikit-learn")

    def test_pages_still_work(self):
        self.assertEqual(self.client.get(SEARCH_PAGE, {"q": "django"}).status_code, 200)
        self.client.force_login(self.learner)
        self.assertEqual(self.client.get(reverse("personalization:recommendations")).status_code, 200)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("personalization:stats")), "pip install scikit-learn")
