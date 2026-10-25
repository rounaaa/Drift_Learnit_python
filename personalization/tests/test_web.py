"""Tests des pages HTML du module Recherche."""
from django.urls import reverse

from personalization.models import Recommendation, SearchHistory, UserPreference
from personalization.templatetags.personalization_tags import duration, highlight

from .base import INFO, MATHS, BaseSearchTestCase

SEARCH_PAGE = reverse("personalization:search")
RECO_PAGE = reverse("personalization:recommendations")
PREF_PAGE = reverse("personalization:preferences")


class HighlightFilterTests(BaseSearchTestCase):
    def test_wraps_each_term_case_insensitively(self):
        self.assertEqual(highlight("Intro Django", "django"), "Intro <mark>Django</mark>")

    def test_escapes_html_before_highlighting(self):
        result = highlight("<script>django</script>", "django")
        self.assertNotIn("<script>", result)
        self.assertIn("<mark>django</mark>", result)

    def test_ignores_one_letter_terms(self):
        self.assertEqual(highlight("a b c", "a"), "a b c")

    def test_duration(self):
        self.assertEqual(duration(600), "10 min")
        self.assertEqual(duration(4500), "1 h 15")
        self.assertEqual(duration(None), "")


class SearchPageTests(BaseSearchTestCase):
    def test_lists_results_with_highlight(self):
        response = self.client.get(SEARCH_PAGE, {"q": "django"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3 résultats pour « django »")  # 2 cours + 1 vidéo
        self.assertContains(response, "<mark>Django</mark>")
        self.assertNotContains(response, "Django brouillon")

    def test_filters_and_sort_are_applied(self):
        response = self.client.get(SEARCH_PAGE, {"type": "course", "level": "BEGINNER", "ordering": "title"})
        self.assertEqual(self.page_titles(response), ["Anglais professionnel", "Django débutant"])

    def test_category_filter_uses_platform_categories(self):
        response = self.client.get(SEARCH_PAGE, {"category": MATHS, "type": "course"})
        self.assertEqual(self.page_titles(response), ["Machine learning"])
        self.assertContains(response, 'value="MATHEMATIQUES"')
        self.assertContains(response, "Mathématiques")

    def test_course_title_links_to_team_detail_page(self):
        response = self.client.get(SEARCH_PAGE, {"q": "anglais"})
        self.assertContains(response, f'href="{reverse("course_detail", args=[self.c_english.pk])}"')

    def test_uses_team_base_template(self):
        response = self.client.get(SEARCH_PAGE)
        self.assertTemplateUsed(response, "base.html")
        self.assertTemplateUsed(response, "personalization/base.html")

    def test_invalid_filter_falls_back_to_defaults(self):
        response = self.client.get(SEARCH_PAGE, {"type": "podcast"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ignorés")

    def test_empty_state(self):
        response = self.client.get(SEARCH_PAGE, {"q": "kubernetes"})
        self.assertContains(response, "Aucun contenu ne correspond à « kubernetes »")

    def test_pagination(self):
        response = self.client.get(SEARCH_PAGE, {"page": 1})
        self.assertEqual(response.context["total_pages"], 1)
        self.assertEqual(len(response.context["items"]), 6)  # 4 cours publiés + 2 vidéos

    def test_history_saved_once_and_shown(self):
        self.client.force_login(self.learner)
        self.client.get(SEARCH_PAGE, {"q": "django"})
        self.client.get(SEARCH_PAGE, {"q": "django", "type": "video"})  # même recherche, autre filtre
        self.client.get(SEARCH_PAGE, {"q": "pandas"})
        self.assertEqual(list(SearchHistory.objects.filter(user=self.learner).values_list("query", flat=True)),
                         ["pandas", "django"])
        response = self.client.get(SEARCH_PAGE, {"q": "osi"})
        self.assertEqual([h.query for h in response.context["recent_searches"]], ["pandas", "django"])

    def test_clear_history(self):
        self.client.force_login(self.learner)
        self.client.get(SEARCH_PAGE, {"q": "django"})
        response = self.client.post(reverse("personalization:clear-history"))
        self.assertRedirects(response, SEARCH_PAGE)
        self.assertFalse(SearchHistory.objects.filter(user=self.learner).exists())

    def test_interests_toggle_for_logged_in_user(self):
        UserPreference.objects.create(user=self.learner, preferred_categories=[MATHS])
        self.client.force_login(self.learner)
        response = self.client.get(SEARCH_PAGE, {"interests": "true", "type": "course"})
        self.assertEqual(self.page_titles(response), ["Machine learning"])


class PreferencesPageTests(BaseSearchTestCase):
    def test_requires_login(self):
        response = self.client.get(PREF_PAGE)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_unknown_category_is_rejected(self):
        self.client.force_login(self.learner)
        response = self.client.post(PREF_PAGE, {"preferred_categories": ["CUISINE"]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserPreference.objects.get(user=self.learner).preferred_categories)

    def test_save_preferences(self):
        self.client.force_login(self.learner)
        response = self.client.post(PREF_PAGE, {"preferred_categories": [INFO], "preferred_level": "ADVANCED"})
        self.assertRedirects(response, RECO_PAGE)
        pref = UserPreference.objects.get(user=self.learner)
        self.assertEqual(pref.preferred_categories, [INFO])
        self.assertEqual(pref.preferred_level, "ADVANCED")
        # Les recommandations ont été recalculées tout de suite.
        top = Recommendation.objects.filter(user=self.learner).order_by("rank").first()
        self.assertEqual(top.course, self.c_django_adv)


class RecommendationsPageTests(BaseSearchTestCase):
    def test_requires_login(self):
        self.assertEqual(self.client.get(RECO_PAGE).status_code, 302)

    def test_shows_ranked_recommendations_and_invite(self):
        self.client.force_login(self.learner)
        response = self.client.get(RECO_PAGE)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choisir mes centres d'intérêt")
        self.assertTrue(len(response.context["recommendations"]) > 0)

    def test_dismiss(self):
        self.client.force_login(self.learner)
        first = self.client.get(RECO_PAGE).context["recommendations"][0]
        response = self.client.post(reverse("personalization:dismiss-recommendation", args=[first.pk]))
        self.assertRedirects(response, RECO_PAGE)
        self.assertTrue(Recommendation.objects.get(pk=first.pk).is_dismissed)

    def test_cannot_dismiss_other_user_recommendation(self):
        self.client.force_login(self.other)
        rec = self.client.get(RECO_PAGE).context["recommendations"][0]
        self.client.force_login(self.learner)
        response = self.client.post(reverse("personalization:dismiss-recommendation", args=[rec.pk]))
        self.assertEqual(response.status_code, 404)

    def test_dismiss_requires_post(self):
        self.client.force_login(self.learner)
        rec = self.client.get(RECO_PAGE).context["recommendations"][0]
        response = self.client.get(reverse("personalization:dismiss-recommendation", args=[rec.pk]))
        self.assertEqual(response.status_code, 405)

    def test_refresh(self):
        self.client.force_login(self.learner)
        response = self.client.post(reverse("personalization:refresh-recommendations"))
        self.assertRedirects(response, RECO_PAGE)
