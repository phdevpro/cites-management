from django import template

register = template.Library()

STATUS_COLORS = {
    "draft": "secondary", "generated": "info", "sent": "primary", "protocolled": "success", "closed": "dark",
    "alive": "success", "dead": "secondary", "transferred": "primary", "lost": "warning", "escaped": "warning",
    "stolen": "danger", "pending": "secondary", "parsed": "warning", "done": "success", "archived": "info",
    "skipped": "light", "error": "danger", "carico": "success", "scarico": "danger",
}


@register.filter
def status_color(value):
    return STATUS_COLORS.get(str(value), "secondary")


@register.filter
def get(d, key):
    try:
        return d.get(key, "")
    except AttributeError:
        return ""


@register.filter
def annex_color(annex):
    return {"A": "danger", "B": "warning", "C": "info", "D": "secondary"}.get(annex, "light")


@register.filter
def absval(value):
    try:
        return abs(int(value))
    except (TypeError, ValueError):
        return value
