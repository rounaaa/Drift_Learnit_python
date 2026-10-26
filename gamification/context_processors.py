def gamification_context(request):
    """
    Rend le profil de gamification disponible dans tous les templates
    si l'utilisateur est authentifié.
    """
    if request.user.is_authenticated:
        try:
            from .services import get_or_create_profile
            return {
                "user_gamification": get_or_create_profile(request.user)
            }
        except Exception:
            return {}
    return {}
