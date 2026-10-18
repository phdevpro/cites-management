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

    return {"LEGAL": settings.LEGAL, "SITE_NAME": settings.SITE_NAME}
