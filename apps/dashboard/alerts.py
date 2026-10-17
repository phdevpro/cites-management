"""Deadline / compliance alerts for a keeper."""

from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.declarations.models import Declaration
from apps.registry.models import Specimen
from apps.species.models import Species

D = settings.CITES_DEADLINES


@dataclass
class Alert:
    level: str  # danger | warning | info
    title: str
    detail: str
    due: date | None
    url: str

    @property
    def days_left(self):
        return (self.due - timezone.localdate()).days if self.due else None


def _level(due: date, today: date, warn_days: int = 5) -> str:
    if due < today:
        return "danger"
    if (due - today).days <= warn_days:
        return "warning"
    return "info"


def keeper_alerts(keeper, today: date | None = None) -> list[Alert]:
    today = today or timezone.localdate()
    out: list[Alert] = []

    open_decls = Declaration.objects.filter(keeper=keeper, status__in=["draft", "generated"])
    for decl in open_decls:
        due = decl.deadline
        out.append(Alert(
            _level(due, today) if due else "info",
            f"Da inviare: {decl.get_kind_display()}",
            f"Evento del {decl.event_date:%d/%m/%Y}" + (f" – scadenza {due:%d/%m/%Y}" if due else ""),
            due, decl.get_absolute_url(),
        ))

    for decl in Declaration.objects.filter(keeper=keeper, status="sent", imported=False):
        if decl.sent_on and (today - decl.sent_on).days > 60:
            out.append(Alert("info", f"Nessuna risposta: {decl.get_kind_display()}",
                             f"Inviata il {decl.sent_on:%d/%m/%Y}: registra il protocollo o sollecita l'ufficio.",
                             None, decl.get_absolute_url()))

    for decl in Declaration.objects.filter(keeper=keeper, kind="SCT3").exclude(status="closed"):
        out.append(Alert("info", "Cessione All. A in corso",
                         f"A {decl.counterparty or '—'}: registra il certificato di spostamento alla consegna.",
                         None, decl.get_absolute_url()))

    unmarked = Specimen.objects.filter(keeper=keeper, status="alive", species__is_testudo=True, markings__isnull=True,
                                       birth_date__isnull=False, species__eu_annex="A")
    for sp in unmarked:
        due = sp.birth_date + timedelta(days=D["testudo_microchip"])
        if (due - today).days <= 60:
            out.append(Alert(_level(due, today, 30), f"Microchip Testudo: {sp}",
                             f"Nato il {sp.birth_date:%d/%m/%Y}: nano microchip entro il primo anno.",
                             due, sp.get_absolute_url()))

    recent_a = Specimen.objects.filter(keeper=keeper, status="alive", origin="born", species__eu_annex="A",
                                       species__is_testudo=False, markings__isnull=True, birth_date__isnull=False,
                                       birth_date__gte=today - timedelta(days=D["marking_details"] + 30))
    for sp in recent_a:
        due = sp.birth_date + timedelta(days=D["marking_details"])
        out.append(Alert(_level(due, today, 10), f"Estremi marcatura: {sp}",
                         "Comunicare gli estremi della marcatura entro 45 gg dalla nascita.", due, sp.get_absolute_url()))

    if keeper.id_doc_expiry and (keeper.id_doc_expiry - today).days <= 30:
        out.append(Alert(_level(keeper.id_doc_expiry, today, 30), "Documento d'identità in scadenza",
                         "Serve una copia valida da allegare alle denunce.", keeper.id_doc_expiry,
                         reverse("accounts:keeper_edit")))

    held = Species.objects.filter(specimens__keeper=keeper, specimens__status="alive",
                                  annex_changed_on__isnull=False, eu_annex="A").distinct()
    for sp in held:
        due = sp.annex_changed_on + timedelta(days=D["annex_a_listing"])
        if due >= today - timedelta(days=30):
            out.append(Alert(_level(due, today, 15), f"{sp} passata in Allegato A",
                             "Denuncia di detenzione entro 90 gg (diritto U669).", due, reverse("registry:specimen_list")))

    if keeper.cites_office is None:
        out.append(Alert("warning", "Ufficio CITES non impostato",
                         "Imposta il Servizio CITES territoriale per compilare i moduli.", None,
                         reverse("accounts:keeper_edit")))

    order = {"danger": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda a: (order[a.level], a.due or date.max))


def keeper_stats(keeper):
    alive = Specimen.objects.filter(keeper=keeper, status="alive")
    year = timezone.localdate().year
    return {
        "alive_total": alive.aggregate(n=Sum("quantity"))["n"] or 0,
        "by_species": alive.values("species__scientific_name", "species__eu_annex").annotate(n=Sum("quantity"))
        .order_by("-n"),
        "born_this_year": Specimen.objects.filter(keeper=keeper, origin="born", birth_date__year=year)
        .aggregate(n=Sum("quantity"))["n"] or 0,
        "dead_this_year": Specimen.objects.filter(keeper=keeper, status="dead", status_date__year=year)
        .aggregate(n=Sum("quantity"))["n"] or 0,
        "transferred_this_year": Specimen.objects.filter(keeper=keeper, status="transferred", status_date__year=year)
        .aggregate(n=Sum("quantity"))["n"] or 0,
    }
