from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from personalization.services.recommendations import refresh_recommendations


class Command(BaseCommand):
    help = "Recalcule les recommandations (US35) de tous les utilisateurs actifs, ou d'un seul."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int, help="ID d'un utilisateur précis")

    def handle(self, *args, **options):
        users = get_user_model().objects.filter(is_active=True)
        if options["user"]:
            users = users.filter(pk=options["user"])
        total = 0
        for user in users:
            total += len(refresh_recommendations(user))
        self.stdout.write(self.style.SUCCESS(f"{total} recommandations générées pour {users.count()} utilisateur(s)."))
