from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, fallback):
    """URL « next » du formulaire si elle pointe vers ce site, sinon fallback (évite les redirections ouvertes)."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return fallback
