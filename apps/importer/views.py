import zipfile
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.declarations.models import Declaration
from apps.registry.models import Specimen
from apps.species.models import Species

from . import services
from .forms import ACTION_BY_KIND, ReviewForm, SheetForm, UploadForm
from .models import ImportBatch, ImportedFile


def _guard(request, edit=True):
    if request.keeper is None:
        raise PermissionDenied("Nessun detentore attivo.")
    if edit and not request.membership.can_edit:
        raise PermissionDenied


def index(request):
    _guard(request, edit=False)
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        _guard(request)
        if form.is_valid():
            batch = ImportBatch.objects.create(keeper=request.keeper, created_by=request.user,
                                               label=form.cleaned_data["label"])
            notes = []
            try:
                for f in form.cleaned_data["files"]:
                    _, msg = services.add_file(batch, f, f.name, f.name, analyze_now=False)
                    if msg:
                        notes.append(msg)
                if form.cleaned_data["archive"]:
                    notes += services.add_zip(batch, form.cleaned_data["archive"], analyze_now=False)
            except zipfile.BadZipFile:
                messages.error(request, "Il file ZIP non è valido o è danneggiato.")
            for n in notes:
                messages.warning(request, n)
            count = batch.files.count()
            if count:
                services.analyze_in_background(batch.pk, request.vault, request.user)
                messages.success(request, f"{count} file caricati e cifrati: analisi in corso.")
            else:
                messages.warning(request, "Nessun file nuovo da analizzare.")
            return redirect("importer:batch", pk=batch.pk)
        messages.error(request, "Controlla i campi del modulo.")
    batches = ImportBatch.objects.filter(keeper=request.keeper)
    pending = ImportedFile.objects.filter(keeper=request.keeper, status__in=["parsed", "error"]).count()
    return render(request, "importer/index.html", {"form": form, "batches": batches, "pending": pending,
                                                   "sheet_form": SheetForm()})


def batch(request, pk):
    _guard(request, edit=False)
    b = get_object_or_404(ImportBatch, pk=pk, keeper=request.keeper)
    if request.method == "POST" and "autoapply" in request.POST:
        _guard(request)
        from .autoapply import auto_apply_batch

        counters = auto_apply_batch(b, request.user)
        labels = {"created": "creati", "linked": "collegati", "duplicate": "già presenti", "archived": "archiviati",
                  "review": "da verificare"}
        summary = ", ".join(f"{n} {labels.get(k, k)}" for k, n in counters.items()) or "nessun documento in sospeso"
        messages.success(request, f"Applicazione automatica: {summary}.")
        return redirect("importer:batch", pk=b.pk)
    if request.method == "POST" and "resume" in request.POST:
        _guard(request)
        services.requeue_stale(b.pk)
        services.analyze_in_background(b.pk, request.vault, request.user)
        messages.info(request, "Analisi ripresa.")
        return redirect("importer:batch", pk=b.pk)
    queue = b.files.filter(status__in=[ImportedFile.Status.PENDING, ImportedFile.Status.PROCESSING]).count()
    total = b.files.count()
    files = b.files.all()
    status = request.GET.get("status")
    if status:
        files = files.filter(status=status)
    return render(request, "importer/batch.html", {
        "batch": b, "files": files, "statuses": ImportedFile.Status.choices,
        "queue": queue, "total": total, "done_pct": int(100 * (total - queue) / total) if total else 100,
        "ai_enabled": services.ai.enabled(request.keeper),
        "to_review": b.files.filter(status=ImportedFile.Status.PARSED).count(),
    })


AI_ACTION = {"birth_declaration": "birth", "death_declaration": "death", "office_reply": "document",
             "movement_certificate": "document", "payment_receipt": "payment"}
AI_RELATED = {"birth": "SCT1", "death": "SCT5", "transfer": "SCT3", "marking": "MARK"}


def _open_doc_index(f: ImportedFile):
    """First AI document of the file still waiting for the user."""
    for i, doc in enumerate((f.parsed or {}).get("documents", [])):
        if (doc.get("result") or {}).get("status") in (None, "review"):
            return i
    return None


def _ai_as_legacy(doc: dict) -> dict:
    """Map an AI document onto the fields the manual review form understands."""
    from .autoapply import DOC_TYPE_FOR

    relates = doc.get("relates_to", "other")
    return {
        "species": doc.get("species"), "quantity": doc.get("quantity") or None,
        "event_date": doc.get("event_date") or doc.get("document_date"), "signed_on": doc.get("document_date"),
        "breeding_group": doc.get("breeding_group", ""),
        "number": doc.get("certificate_number") or doc.get("protocol_number"),
        "doc_type": "art9" if doc.get("certificate_number") else DOC_TYPE_FOR.get(relates, "other"),
        "issued_on": doc.get("document_date"), "paid_on": doc.get("document_date"),
        "amount": doc.get("amount_eur") or None, "related_kind": AI_RELATED.get(relates, ""),
    }


def _initial(f: ImportedFile, doc_index=None):
    d = (f.parsed or {}).get("data", {})
    kind = f.detected_kind
    if (f.parsed or {}).get("ai"):
        docs = f.parsed.get("documents", [])
        if doc_index is not None and 0 <= doc_index < len(docs):
            d = _ai_as_legacy(docs[doc_index])
            ai_action = AI_ACTION.get(docs[doc_index].get("type"), "archive")
            initial = _initial_from(d, ai_action)
            return initial
    return _initial_from(d, ACTION_BY_KIND.get(kind, "archive"))


def _initial_from(d: dict, action: str):
    initial = {"action": action, "quantity": d.get("quantity") or None,
               "breeding_group": d.get("breeding_group", ""), "number": d.get("number") or d.get("certificate_number", ""),
               "doc_type": d.get("doc_type") or "other", "amount": d.get("amount"), "notes": ""}
    for key in ("event_date", "signed_on", "issued_on", "paid_on"):
        if d.get(key):
            try:
                initial[key] = date.fromisoformat(d[key])
            except ValueError:
                pass
    if d.get("species"):
        sp = Species.objects.filter(scientific_name__iexact=d["species"]).first()
        if sp:
            initial["species"] = sp.pk
    if d.get("certificate_number") and d.get("number"):
        initial["notes"] = f"Certificato {d['certificate_number']}"
    return initial


def review(request, pk):
    _guard(request, edit=False)
    f = get_object_or_404(ImportedFile, pk=pk, keeper=request.keeper)
    is_ai = bool((f.parsed or {}).get("ai"))
    raw_index = request.POST.get("doc_index") or request.GET.get("doc")
    doc_index = int(raw_index) if raw_index and raw_index.isdigit() else (_open_doc_index(f) if is_ai else None)
    form = ReviewForm(request.POST or None, keeper=request.keeper, initial=_initial(f, doc_index))
    if request.method == "POST":
        _guard(request)
        if "reanalyze" in request.POST:
            services.analyze(f)
            messages.info(request, "File rianalizzato.")
            return redirect("importer:review", pk=pk)
        if is_ai and "ignore_doc" in request.POST and doc_index is not None:
            _resolve_doc(f, doc_index, {"status": "archived", "message": "Ignorato dall'utente."})
            return redirect("importer:review", pk=pk)
        if form.is_valid():
            try:
                msg = services.apply(f, form.cleaned_data, request.user)
            except Exception as exc:
                messages.error(request, f"Errore: {exc}")
            else:
                messages.success(request, msg)
                if is_ai and doc_index is not None:
                    _resolve_doc(ImportedFile.objects.get(pk=f.pk), doc_index,
                                 {"status": "created", "message": f"Registrato manualmente: {msg}"})
                    if _open_doc_index(ImportedFile.objects.get(pk=f.pk)) is not None:
                        return redirect("importer:review", pk=pk)
                nxt = (ImportedFile.objects.filter(batch=f.batch, status="parsed").exclude(pk=f.pk).first())
                return redirect("importer:review", pk=nxt.pk) if nxt else redirect("importer:batch", pk=f.batch_id)
    d = (f.parsed or {}).get("data", {})
    if is_ai and doc_index is not None and doc_index < len(f.parsed.get("documents", [])):
        d = _ai_as_legacy(f.parsed["documents"][doc_index])
    candidates = []
    if d.get("related_kind") and d.get("species"):
        candidates = Declaration.objects.filter(keeper=request.keeper, kind__startswith=d["related_kind"][:4],
                                                items__specimen__species__scientific_name__iexact=d["species"]
                                                ).distinct()[:10]
    death_candidates = []
    if (form.initial.get("action") == "death" or f.detected_kind == "SCT5") and d.get("species"):
        death_candidates = Specimen.objects.filter(keeper=request.keeper, status="alive",
                                                   species__scientific_name__iexact=d["species"])[:20]
    siblings = list(f.batch.files.values_list("pk", flat=True))
    idx = siblings.index(f.pk)
    return render(request, "importer/review.html", {
        "f": f, "form": form, "parsed": f.parsed or {}, "candidates": candidates, "is_ai": is_ai,
        "doc_index": doc_index,
        "death_candidates": death_candidates,
        "prev_pk": siblings[idx - 1] if idx > 0 else None,
        "next_pk": siblings[idx + 1] if idx + 1 < len(siblings) else None,
    })


def _resolve_doc(f: ImportedFile, index: int, result: dict):
    from .autoapply import file_status

    f.parsed["documents"][index]["result"] = result
    f.status = file_status(f.parsed)
    f.save(update_fields=["parsed", "status", "updated_at"])


def file_view(request, pk):
    _guard(request, edit=False)
    f = get_object_or_404(ImportedFile, pk=pk, keeper=request.keeper)
    return FileResponse(f.file.open("rb"), filename=f.original_name, as_attachment=False)  # decrypted by storage


def sheet_template(request):
    resp = HttpResponse(services.sheet_template(),
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="esemplari_modello.xlsx"'
    return resp


def sheet_import(request):
    _guard(request)
    form = SheetForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        count, errors = services.import_specimen_sheet(request.keeper, request.user, form.cleaned_data["file"])
        for e in errors:
            messages.warning(request, e)
        messages.success(request, f"{count} righe importate.")
        return redirect("registry:specimen_list")
    return redirect("importer:index")


def _ids(request, name="ids"):
    return [int(x) for x in request.POST.getlist(name) if x.isdigit()]


@require_POST
def delete_batches(request):
    """Delete whole imports: the selected ones, or all of them."""
    _guard(request)
    batches = ImportBatch.objects.filter(keeper=request.keeper)
    if "all" not in request.POST:
        batches = batches.filter(pk__in=_ids(request))
    n_batches = batches.count()
    n_files = services.delete_batches(batches)
    messages.success(request, f"Eliminati {n_batches} import ({n_files} file).")
    return redirect("importer:index")


@require_POST
def delete_files(request, pk):
    """Delete selected files of an import (or the whole import)."""
    _guard(request)
    b = get_object_or_404(ImportBatch, pk=pk, keeper=request.keeper)
    if "whole" in request.POST:
        n = services.delete_batches([b])
        messages.success(request, f"Import eliminato ({n} file).")
        return redirect("importer:index")
    n = services.delete_imports(b.files.filter(pk__in=_ids(request)))
    messages.success(request, f"Eliminati {n} file.")
    return redirect("importer:batch", pk=b.pk)
