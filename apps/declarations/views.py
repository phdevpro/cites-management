import io
import zipfile
from pathlib import Path

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.accounts.mixins import KeeperRequiredMixin
from apps.pdfforms.envelope import envelope_pdf
from apps.pdfforms.formdata import FORM_SPECS, build_form_data, get_form_data
from apps.pdfforms.render import output_options, render_declaration, render_pdf
from apps.vault.storage import read_plain

from . import services
from .forms import (AttachmentForm, BirthForm, CompleteTransferForm, DeathForm, DeclarationMetaForm, LossForm,
                    NewbornFormSet, PaymentForm, PdfOptionsForm, ProtocolForm, SentForm, TransferForm)
from .models import Declaration, Payment


def _guard(request, edit=True):
    if request.keeper is None:
        raise PermissionDenied("Nessun detentore attivo.")
    if edit and not request.membership.can_edit:
        raise PermissionDenied("Permesso di sola lettura.")


def _get(request, pk) -> Declaration:
    return get_object_or_404(Declaration, pk=pk, keeper=request.keeper)


class DeclarationList(KeeperRequiredMixin, ListView):
    model = Declaration
    template_name = "declarations/list.html"
    paginate_by = 50

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related("items__specimen__species")
        for param, fld in (("kind", "kind"), ("status", "status")):
            if self.request.GET.get(param):
                qs = qs.filter(**{fld: self.request.GET[param]})
        if self.request.GET.get("year"):
            qs = qs.filter(event_date__year=self.request.GET["year"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["kinds"] = Declaration.Kind.choices
        ctx["statuses"] = Declaration.Status.choices
        ctx["years"] = Declaration.objects.filter(keeper=self.request.keeper).dates("event_date", "year", "DESC")
        return ctx


def detail(request, pk):
    _guard(request, edit=False)
    decl = _get(request, pk)
    ctx = {
        "decl": decl,
        "items": decl.items.select_related("specimen__species", "document"),
        "attachments": decl.attachments.all(),
        "payments": decl.payments.all(),
        "sent_form": SentForm(initial={"sent_on": timezone.localdate(), "channel": "pec"}),
        "protocol_form": ProtocolForm(),
        "attachment_form": AttachmentForm(),
        "complete_form": CompleteTransferForm(initial={"completed_on": timezone.localdate()}),
        "imported_files": decl.imported_files.all(),
        "spec": FORM_SPECS.get(decl.kind),
    }
    return render(request, "declarations/detail.html", ctx)


# --------------------------------------------------------------------------- wizards

def new_birth(request):
    _guard(request)
    form = BirthForm(request.POST or None, keeper=request.keeper)
    formset = NewbornFormSet(request.POST or None, prefix="rows",
                             initial=None if request.method == "POST" else [{"quantity": 1}])
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        cd = form.cleaned_data
        rows = [services.NewbornSpec(**{k: v for k, v in f.cleaned_data.items() if k != "DELETE"})
                for f in formset.forms if f.cleaned_data]
        try:
            result = services.register_birth(
                keeper=request.keeper, user=request.user, species=cd["species"], birth_date=cd["birth_date"],
                rows=rows, father=cd["father"], mother=cd["mother"], breeding_group=cd["breeding_group"],
            )
        except services.ServiceError as exc:
            messages.error(request, str(exc))
        else:
            n = sum(r.quantity for r in rows)
            messages.success(request, f"Registrati {n} nati. Scadenza denuncia: {result.declaration.deadline:%d/%m/%Y}."
                             if result.declaration else f"Registrati {n} nati (specie non soggetta a denuncia).")
            return redirect(result.declaration or "registry:specimen_list")
    return render(request, "declarations/new_birth.html", {"form": form, "formset": formset})


def new_death(request):
    _guard(request)
    initial = {"death_date": timezone.localdate()}
    if request.GET.get("specimen"):
        initial["specimen"] = request.GET["specimen"]
    form = DeathForm(request.POST or None, keeper=request.keeper, initial=initial)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            decl = services.register_death(keeper=request.keeper, user=request.user, specimen=cd["specimen"],
                                           quantity=cd["quantity"], death_date=cd["death_date"], cause=cd["cause"])
        except services.ServiceError as exc:
            messages.error(request, str(exc))
        else:
            if decl:
                messages.success(request, "Decesso registrato. Prepara e invia il modello SCT5 restituendo i certificati.")
                return redirect(decl)
            messages.success(request, "Decesso registrato nel registro di scarico.")
            return redirect("registry:specimen_list")
    return render(request, "form.html", {"form": form, "title": "Registra decesso"})


def new_loss(request):
    _guard(request)
    initial = {"death_date": timezone.localdate()}
    if request.GET.get("specimen"):
        initial["specimen"] = request.GET["specimen"]
    form = LossForm(request.POST or None, keeper=request.keeper, initial=initial)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            decl = services.register_loss(keeper=request.keeper, user=request.user, specimen=cd["specimen"],
                                          quantity=cd["quantity"], event_date=cd["death_date"], status=cd["status"],
                                          circumstances=cd["circumstances"])
        except services.ServiceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Evento registrato. Prepara la comunicazione al Servizio CITES.")
            return redirect(decl)
    return render(request, "form.html", {"form": form, "title": "Smarrimento / fuga / furto"})


def new_transfer(request):
    _guard(request)
    initial = {"transfer_date": timezone.localdate()}
    if request.GET.get("specimen"):
        initial["specimens"] = [request.GET["specimen"]]
    form = TransferForm(request.POST or None, keeper=request.keeper, initial=initial)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        qty = form.quantities(request.POST)
        lines = [services.TransferLine(specimen=sp, quantity=qty[sp.pk]) for sp in cd["specimens"]]
        try:
            decl = services.start_transfer(keeper=request.keeper, user=request.user, lines=lines,
                                           counterparty=cd["counterparty"], transfer_date=cd["transfer_date"],
                                           is_sale=cd["is_sale"])
        except services.ServiceError as exc:
            messages.error(request, str(exc))
        else:
            if decl.kind == Declaration.Kind.TRANSFER:
                messages.info(request, "Cessione All. A: invia l'SCT3 con ricevuta del diritto (W802) e documenti "
                                       "d'identità. Gli esemplari restano in carico fino al rilascio del certificato.")
            else:
                messages.success(request, "Cessione All. B registrata e scaricata dal registro.")
            return redirect(decl)
    return render(request, "declarations/new_transfer.html", {"form": form})


# --------------------------------------------------------------------------- form data / PDF

def edit_form_data(request, pk):
    _guard(request)
    decl = _get(request, pk)
    spec = FORM_SPECS[decl.kind]
    if request.method == "POST":
        if "reset" in request.POST:
            decl.data.pop("form", None)
            decl.save(update_fields=["data"])
            messages.info(request, "Dati ricalcolati dall'archivio.")
            return redirect("declarations:edit_form", pk=pk)
        meta = DeclarationMetaForm(request.POST, instance=decl)
        if meta.is_valid():
            meta.save()
        fields = {}
        for f in spec.fields:
            if f.kind == "bool":
                fields[f.key] = f"f__{f.key}" in request.POST
            else:
                fields[f.key] = request.POST.get(f"f__{f.key}", "").strip()
        rows = []
        n_rows = int(request.POST.get("n_rows", 0)) + (1 if "add_row" in request.POST else 0)
        for i in range(n_rows):
            if f"del__{i}" in request.POST:
                continue
            row = {col: request.POST.get(f"r__{i}__{col}", "").strip() for col, _ in spec.row_columns}
            if any(row.values()) or ("add_row" in request.POST and i == n_rows - 1):
                rows.append(row)
        decl.data["form"] = {"fields": fields, "rows": rows}
        decl.save(update_fields=["data"])
        if "add_row" in request.POST:
            return redirect("declarations:edit_form", pk=pk)
        if "generate" in request.POST:
            return generate(request, pk)
        messages.success(request, "Dati modulo salvati.")
        return redirect(decl)
    data = get_form_data(decl)
    fields = [(f, data["fields"].get(f.key, "")) for f in spec.fields]
    return render(request, "declarations/edit_form.html", {
        "decl": decl, "spec": spec, "fields": fields, "rows": data.get("rows", []),
        "meta_form": DeclarationMetaForm(instance=decl),
        "rows_per_page": spec.rows_per_page,
    })


def _filename(decl):
    who = slugify(decl.keeper.last_name or str(decl.keeper))
    return f"{decl.kind}_{decl.event_date:%Y%m%d}_{who}.pdf"


def _missing_attachments(decl) -> bool:
    opts = output_options(decl)
    keeper = decl.keeper
    return (opts["signature"] and not keeper.signature) or (opts["id_doc"] and not keeper.id_doc_file)


def pdf_options(request, pk):
    """Signature / identity document for the generated PDF; asked automatically when one is missing."""
    _guard(request)
    decl = _get(request, pk)
    keeper = decl.keeper
    can_upload = request.membership.role == "owner"
    opts = output_options(decl)
    bound = request.method == "POST"
    form = PdfOptionsForm(request.POST if bound else None, request.FILES if bound else None, keeper=keeper,
                          can_upload=can_upload,
                          initial={"include_signature": opts["signature"] and (bool(keeper.signature) or can_upload),
                                   "include_id": opts["id_doc"] and (bool(keeper.id_doc_file) or can_upload)})
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        changed = []
        if cd.get("signature"):
            keeper.signature = cd["signature"]
            changed.append("signature")
        if cd.get("id_doc"):
            keeper.id_doc_file = cd["id_doc"]
            changed.append("id_doc_file")
        if changed:
            keeper.save(update_fields=changed)
            messages.success(request, "Salvato nel profilo (cifrato).")
        decl.data["output"] = {"signature": cd["include_signature"], "id_doc": cd["include_id"]}
        decl.save(update_fields=["data"])
        return generate(request, pk)
    expired = keeper.id_doc_expiry and keeper.id_doc_expiry < timezone.localdate()
    return render(request, "declarations/pdf_options.html", {
        "decl": decl, "form": form, "keeper": keeper, "can_upload": can_upload, "id_expired": expired,
    })


def generate(request, pk):
    _guard(request)
    decl = _get(request, pk)
    if _missing_attachments(decl):
        return redirect("declarations:pdf_options", pk=pk)  # ask before producing an unsigned PDF
    if "form" not in decl.data:
        decl.data["form"] = build_form_data(decl)
    decl.save(update_fields=["data"])
    pdf = render_declaration(decl)
    if decl.pdf:
        decl.pdf.delete(save=False)
    decl.pdf.save(_filename(decl), ContentFile(pdf), save=False)
    if decl.status == Declaration.Status.DRAFT:
        decl.status = Declaration.Status.GENERATED
    decl.save()
    opts = output_options(decl)
    signed = opts["signature"] and bool(decl.keeper.signature)
    with_id = opts["id_doc"] and bool(decl.keeper.id_doc_file)
    if signed and with_id:
        messages.success(request, "PDF generato, firmato e con il documento d'identità allegato: pronto da inviare.")
    else:
        todo = [t for t, ok in (("firmalo", signed), ("allega copia del documento d'identità", with_id)) if not ok]
        messages.success(request, f"PDF generato: {' e '.join(todo)} prima dell'invio.")
    return redirect(decl)


def preview(request, pk):
    _guard(request, edit=False)
    decl = _get(request, pk)
    pdf = render_declaration(decl)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{_filename(decl)}"'
    return resp


def download(request, pk):
    _guard(request, edit=False)
    decl = _get(request, pk)
    if not decl.pdf:
        raise Http404("PDF non ancora generato")
    return FileResponse(decl.pdf.open("rb"), filename=_filename(decl), as_attachment=False)


def envelope(request, pk):
    _guard(request, edit=False)
    decl = _get(request, pk)
    pdf = envelope_pdf(decl.keeper, decl.office, decl.get_kind_display())
    return HttpResponse(pdf, content_type="application/pdf")


def bundle(request, pk):
    """ZIP with everything to send/keep: form, attachments, receipts, counterparty ID, checklist."""
    _guard(request, edit=False)
    decl = _get(request, pk)
    buf = io.BytesIO()
    checklist = [f"Pratica: {decl.get_kind_display()} – evento {decl.event_date:%d/%m/%Y}", ""]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_filename(decl), render_declaration(decl))
        opts = output_options(decl)
        signed = opts["signature"] and bool(decl.keeper.signature)
        id_in_pdf = opts["id_doc"] and bool(decl.keeper.id_doc_file)
        checklist.append(f"[{'x' if signed else ' '}] Modulo compilato e FIRMATO")
        for n, att in enumerate(decl.attachments.all(), start=1):
            name = slugify(Path(att.description).stem) or f"allegato-{n}"
            zf.writestr(f"allegati/{n:02d}_{name}{Path(att.file.name).suffix}", read_plain(att.file))
        for n, pay in enumerate(decl.payments.exclude(receipt=""), start=1):
            zf.writestr(f"pagamenti/ricevuta_{n:02d}{Path(pay.receipt.name).suffix}", read_plain(pay.receipt))
        if decl.keeper.id_doc_file:
            zf.writestr(f"documento_detentore{Path(decl.keeper.id_doc_file.name).suffix}",
                        read_plain(decl.keeper.id_doc_file))
        checklist.append(f"[{'x' if decl.keeper.id_doc_file else ' '}] Copia documento d'identità del dichiarante"
                         + (" (già in coda al PDF)" if id_in_pdf else ""))
        if decl.kind == Declaration.Kind.TRANSFER:
            cp = decl.counterparty
            if cp and cp.id_doc_file:
                zf.writestr(f"documento_cessionario{Path(cp.id_doc_file.name).suffix}", read_plain(cp.id_doc_file))
            checklist += [
                f"[{'x' if cp and cp.id_doc_file else ' '}] Copia documento d'identità del cessionario",
                f"[{'x' if decl.payments.exists() else ' '}] Ricevuta diritto speciale di prelievo (cod. W802)",
                "[ ] Copia dei certificati/documenti CITES degli esemplari",
                "[ ] Parte 2 SCT3 compilata e firmata dal destinatario",
            ]
        if decl.kind == Declaration.Kind.DEATH:
            checklist.append("[ ] Certificati originali degli esemplari deceduti da RESTITUIRE")
        checklist += ["", "Invio: PEC / raccomandata A/R / consegna a mano al Servizio CITES territoriale."]
        if decl.office:
            checklist.append(f"Ufficio: {decl.office.name} – {decl.office.address} – PEC {decl.office.pec}")
        zf.writestr("CHECKLIST.txt", "\n".join(checklist))
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="{Path(_filename(decl)).stem}.zip"'
    return resp


# --------------------------------------------------------------------------- status

@require_POST
def mark_sent(request, pk):
    _guard(request)
    decl = _get(request, pk)
    form = SentForm(request.POST)
    if form.is_valid():
        services.mark_sent(decl, form.cleaned_data["sent_on"], form.cleaned_data["channel"])
        messages.success(request, "Segnata come inviata.")
    return redirect(decl)


@require_POST
def mark_protocolled(request, pk):
    _guard(request)
    decl = _get(request, pk)
    form = ProtocolForm(request.POST, request.FILES)
    if form.is_valid():
        with transaction.atomic():
            services.mark_protocolled(decl, form.cleaned_data["protocol_number"], form.cleaned_data["protocol_date"])
            if form.cleaned_data["reply_file"]:
                decl.attachments.create(kind="reply", file=form.cleaned_data["reply_file"],
                                        description=f"Protocollo {form.cleaned_data['protocol_number']}")
        messages.success(request, "Protocollo registrato e collegato agli esemplari.")
    else:
        messages.error(request, "Dati protocollo non validi.")
    return redirect(decl)


@require_POST
def complete_transfer(request, pk):
    _guard(request)
    decl = _get(request, pk)
    form = CompleteTransferForm(request.POST, request.FILES)
    if form.is_valid():
        cd = form.cleaned_data
        try:
            services.complete_transfer(declaration=decl, user=request.user, completed_on=cd["completed_on"],
                                       certificate_number=cd["certificate_number"],
                                       certificate_date=cd["certificate_date"],
                                       certificate_file=cd["certificate_file"])
        except services.ServiceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Cessione completata: esemplari scaricati dal registro.")
    return redirect(decl)


@require_POST
def add_attachment(request, pk):
    _guard(request)
    decl = _get(request, pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        att = form.save(commit=False)
        att.declaration = decl
        att.save()
        messages.success(request, "Allegato caricato.")
    return redirect(decl)


@require_POST
def delete(request, pk):
    """Delete a declaration and undo its effects on the registry (see services.delete_declaration)."""
    _guard(request)
    decl = _get(request, pk)
    try:
        messages.success(request, services.delete_declaration(decl, request.user))
    except services.ServiceError as exc:
        messages.error(request, str(exc))
        return redirect(decl)
    return redirect("declarations:list")


@require_POST
def delete_many(request):
    """Bulk delete from the list. Newest first, so later events are removed before what they depend on."""
    _guard(request)
    ids = [int(x) for x in request.POST.getlist("ids") if x.isdigit()]
    done, errors = 0, []
    for decl in Declaration.objects.filter(keeper=request.keeper, pk__in=ids).order_by("-event_date", "-pk"):
        try:
            services.delete_declaration(decl, request.user)
            done += 1
        except services.ServiceError as exc:
            errors.append(f"{decl.get_kind_display()} del {decl.event_date:%d/%m/%Y}: {exc}")
    if done:
        messages.success(request, f"Eliminate {done} pratiche.")
    for e in errors:
        messages.error(request, e)
    return redirect("declarations:list")


# --------------------------------------------------------------------------- payments

class PaymentList(KeeperRequiredMixin, ListView):
    model = Payment
    template_name = "declarations/payments.html"


def payment_edit(request, pk=None):
    _guard(request)
    pay = get_object_or_404(Payment, pk=pk, keeper=request.keeper) if pk else None
    initial = {"paid_on": timezone.localdate()}
    if request.GET.get("declaration"):
        initial["declaration"] = request.GET["declaration"]
    form = PaymentForm(request.POST or None, request.FILES or None, instance=pay, keeper=request.keeper,
                       initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.keeper = request.keeper
        obj.save()
        messages.success(request, "Pagamento salvato.")
        return redirect(obj.declaration or "declarations:payments")
    return render(request, "form.html", {"form": form, "title": "Pagamento diritto speciale di prelievo",
                                         "help": "Pagamento con codice pratica su poste.it (Pagamenti → "
                                                 "Amministrazioni statali) o in ufficio postale."})

