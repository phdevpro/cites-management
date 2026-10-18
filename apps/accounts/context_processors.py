def keeper(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {
        "current_keeper": getattr(request, "keeper", None),
        "current_membership": getattr(request, "membership", None),
        "my_memberships": request.user.memberships.select_related("keeper"),
    }


def legal(request):
    from django.conf import settings

    from apps.importer import ai

    keeper = getattr(request, "keeper", None)
    return {"LEGAL": settings.LEGAL, "SITE_NAME": settings.SITE_NAME, "ALLOW_SIGNUP": settings.ALLOW_SIGNUP,
            "ADMIN_URL": "/" + settings.ADMIN_URL,
            "AI_PROVIDER": "Regolo.ai (Seeweb S.r.l.)" if ai.enabled(keeper) else ""}
