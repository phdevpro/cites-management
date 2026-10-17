from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

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
            for f in form.cleaned_data["files"]:
                _, msg = services.add_file(batch, f, f.name, f.name)
                if msg:
                    notes.append(msg)
            if form.cleaned_data["archive"]:
                notes += services.add_zip(batch, form.cleaned_data["archive"])
            for n in notes:
                messages.warning(request, n)
            messages.success(request, f"{batch.files.count()} file analizzati.")
            return redirect("importer:batch", pk=batch.pk)
    batches = ImportBatch.objects.filter(keeper=request.keeper)
    pending = ImportedFile.objects.filter(keeper=request.keeper, status__in=["parsed", "error"]).count()
    return render(request, "importer/index.html", {"form": form, "batches": batches, "pending": pending,
                                                   "sheet_form": SheetForm()})


def batch(request, pk):
    _guard(request, edit=False)
    b = get_object_or_404(ImportBatch, pk=pk, keeper=request.keeper)
    files = b.files.all()
    status = request.GET.get("status")
    if status:
        files = files.filter(status=status)
    return render(request, "importer/batch.html", {"batch": b, "files": files, "statuses": ImportedFile.Status.choices})


def _initial(f: ImportedFile):
    d = (f.parsed or {}).get("data", {})
    kind = f.detected_kind
    initial = {"action": ACTION_BY_KIND.get(kind, "archive"), "quantity": d.get("quantity") or None,
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
    form = ReviewForm(request.POST or None, keeper=request.keeper, initial=_initial(f))
    if request.method == "POST":
        _guard(request)
        if "reanalyze" in request.POST:
            services.analyze(f)
            messages.info(request, "File rianalizzato.")
            return redirect("importer:review", pk=pk)
        if form.is_valid():
            try:
                msg = services.apply(f, form.cleaned_data, request.user)
            except Exception as exc:
                messages.error(request, f"Errore: {exc}")
            else:
                messages.success(request, msg)
                nxt = (ImportedFile.objects.filter(batch=f.batch, status="parsed").exclude(pk=f.pk).first())
                return redirect("importer:review", pk=nxt.pk) if nxt else redirect("importer:batch", pk=f.batch_id)
    d = (f.parsed or {}).get("data", {})
    candidates = []
    if d.get("related_kind") and d.get("species"):
        candidates = Declaration.objects.filter(keeper=request.keeper, kind__startswith=d["related_kind"][:4],
                                                items__specimen__species__scientific_name__iexact=d["species"]
                                                ).distinct()[:10]
    death_candidates = []
    if f.detected_kind == "SCT5" and d.get("species"):
        death_candidates = Specimen.objects.filter(keeper=request.keeper, status="alive",
                                                   species__scientific_name__iexact=d["species"])[:20]
    siblings = list(f.batch.files.values_list("pk", flat=True))
    idx = siblings.index(f.pk)
    return render(request, "importer/review.html", {
        "f": f, "form": form, "parsed": f.parsed or {}, "candidates": candidates,
        "death_candidates": death_candidates,
        "prev_pk": siblings[idx - 1] if idx > 0 else None,
        "next_pk": siblings[idx + 1] if idx + 1 < len(siblings) else None,
    })


def file_view(request, pk):
    _guard(request, edit=False)
    f = get_object_or_404(ImportedFile, pk=pk, keeper=request.keeper)
    return FileResponse(f.file.open("rb"), filename=f.original_name, as_attachment=False)


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
