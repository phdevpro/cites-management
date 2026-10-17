from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.accounts.mixins import KeeperEditMixin, KeeperRequiredMixin
from apps.declarations import services
from apps.species.models import Species

from . import exports
from .forms import AcquisitionForm, CitesDocumentForm, CounterpartyForm, MarkingForm, SpecimenForm, SplitForm
from .models import CitesDocument, Counterparty, Marking, RegisterEntry, Specimen


class KeeperFormKwargsMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["keeper"] = self.request.keeper
        return kwargs

    def form_valid(self, form):
        form.instance.keeper = self.request.keeper
        return super().form_valid(form)


# --------------------------------------------------------------------------- specimens

class SpecimenList(KeeperRequiredMixin, ListView):
    model = Specimen
    paginate_by = 50
    template_name = "registry/specimen_list.html"

    def get_queryset(self):
        qs = super().get_queryset().select_related("species").prefetch_related("markings")
        status = self.request.GET.get("status", "alive")
        if status != "all":
            qs = qs.filter(status=status)
        if self.request.GET.get("species"):
            qs = qs.filter(species_id=self.request.GET["species"])
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(markings__code__icontains=q) | Q(notes__icontains=q)
                           | Q(species__scientific_name__icontains=q)).distinct()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["statuses"] = Specimen.Status.choices
        ctx["species_list"] = Species.objects.filter(specimens__keeper=self.request.keeper).distinct()
        ctx["totals"] = (
            Specimen.objects.filter(keeper=self.request.keeper, status="alive")
            .values("species__scientific_name", "species__eu_annex")
            .annotate(n=Sum("quantity"))
            .order_by("species__scientific_name")
        )
        return ctx


class SpecimenDetail(KeeperRequiredMixin, DetailView):
    model = Specimen
    template_name = "registry/specimen_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sp = self.object
        ctx["documents"] = sp.cites_documents.all()
        ctx["declarations"] = (
            sp.declaration_items.select_related("declaration").order_by("-declaration__event_date")
        )
        ctx["register"] = sp.register_entries.all()
        ctx["history"] = sp.history.all()[:30]
        ctx["offspring"] = sp.offspring.select_related("species")
        ctx["splits"] = sp.splits.all()
        ctx["marking_form"] = MarkingForm()
        ctx["split_form"] = SplitForm()
        return ctx


class SpecimenUpdate(KeeperEditMixin, KeeperFormKwargsMixin, UpdateView):
    model = Specimen
    form_class = SpecimenForm
    template_name = "form.html"
    extra_context = {"title": "Modifica esemplare"}


def _keeper_guard(request):
    from django.core.exceptions import PermissionDenied

    if request.keeper is None or not request.membership.can_edit:
        raise PermissionDenied


def specimen_add(request):
    """Add animals already kept or acquired (carico)."""
    if request.keeper is None:
        return redirect("accounts:keeper_create")
    _keeper_guard(request)
    form = AcquisitionForm(request.POST or None, keeper=request.keeper)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        doc = None
        if cd["doc_type"] and cd["doc_number"]:
            doc = CitesDocument.objects.create(
                keeper=request.keeper, doc_type=cd["doc_type"], number=cd["doc_number"], issued_on=cd["doc_date"]
            )
        sp = services.register_acquisition(
            keeper=request.keeper, user=request.user, species=cd["species"], quantity=cd["quantity"],
            acquired_on=cd["acquired_on"], counterparty=cd["counterparty"], sex=cd["sex"],
            birth_date=cd["birth_date"], name=cd["name"], marking_kind=cd["marking_kind"],
            marking_code=cd["marking_code"], document=doc, origin=cd["origin"],
        )
        messages.success(request, f"{sp} aggiunto al registro (carico).")
        return redirect(sp)
    return render(request, "form.html", {"form": form, "title": "Aggiungi esemplari detenuti / acquisiti"})


def specimen_marking(request, pk):
    _keeper_guard(request)
    sp = get_object_or_404(Specimen, pk=pk, keeper=request.keeper)
    form = MarkingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            decl = services.add_marking(
                keeper=request.keeper, user=request.user, specimen=sp, kind=cd["kind"], code=cd["code"],
                manufacturer=cd["manufacturer"], applied_on=cd["applied_on"], applied_by=cd["applied_by"],
                notify=cd["notify"],
            )
        except Exception as exc:
            messages.error(request, f"Errore: {exc}")
            return redirect(sp)
        messages.success(request, "Marcatura registrata.")
        if decl:
            return redirect(decl)
        return redirect(sp)
    return render(request, "form.html", {"form": form, "title": f"Marcatura – {sp}"})


def specimen_split(request, pk):
    _keeper_guard(request)
    sp = get_object_or_404(Specimen, pk=pk, keeper=request.keeper)
    form = SplitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            part = services.split_lot(sp, form.cleaned_data["quantity"])
        except services.ServiceError as exc:
            messages.error(request, str(exc))
            return redirect(sp)
        if form.cleaned_data["name"]:
            part.name = form.cleaned_data["name"]
            part.save(update_fields=["name"])
        messages.success(request, f"Separato: {part}")
        return redirect(part)
    return render(request, "form.html", {"form": form, "title": f"Separa lotto – {sp}"})


def pedigree(request, pk):
    if request.keeper is None:
        return redirect("accounts:keeper_create")
    sp = get_object_or_404(Specimen.objects.select_related("father", "mother"), pk=pk, keeper=request.keeper)

    def ancestors(node, depth):
        if node is None or depth == 0:
            return None
        return {"node": node, "father": ancestors(node.father, depth - 1), "mother": ancestors(node.mother, depth - 1)}

    return render(request, "registry/pedigree.html", {"specimen": sp, "tree": ancestors(sp, 4),
                                                     "offspring": sp.offspring.select_related("species")})


# --------------------------------------------------------------------------- counterparties

class CounterpartyList(KeeperRequiredMixin, ListView):
    model = Counterparty
    template_name = "registry/counterparty_list.html"

    def get_queryset(self):
        return super().get_queryset().annotate(
            n_in=Count("specimens_sold", distinct=True), n_out=Count("specimens_bought", distinct=True)
        )


class CounterpartyCreate(KeeperEditMixin, CreateView):
    model = Counterparty
    form_class = CounterpartyForm
    template_name = "form.html"
    extra_context = {"title": "Nuova controparte (cedente / cessionario)"}
    success_url = reverse_lazy("registry:counterparty_list")

    def form_valid(self, form):
        form.instance.keeper = self.request.keeper
        resp = super().form_valid(form)
        nxt = self.request.GET.get("next")
        return redirect(nxt) if nxt and nxt.startswith("/") else resp


class CounterpartyUpdate(KeeperEditMixin, UpdateView):
    model = Counterparty
    form_class = CounterpartyForm
    template_name = "form.html"
    extra_context = {"title": "Modifica controparte"}
    success_url = reverse_lazy("registry:counterparty_list")


# --------------------------------------------------------------------------- CITES documents

class DocumentList(KeeperRequiredMixin, ListView):
    model = CitesDocument
    template_name = "registry/document_list.html"
    paginate_by = 50

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related("specimens__species")
        if self.request.GET.get("type"):
            qs = qs.filter(doc_type=self.request.GET["type"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["types"] = CitesDocument.DocType.choices
        return ctx


class DocumentCreate(KeeperEditMixin, KeeperFormKwargsMixin, CreateView):
    model = CitesDocument
    form_class = CitesDocumentForm
    template_name = "form.html"
    extra_context = {"title": "Nuovo documento CITES"}
    success_url = reverse_lazy("registry:document_list")

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("specimen"):
            initial["specimens"] = [self.request.GET["specimen"]]
        return initial


class DocumentUpdate(KeeperEditMixin, KeeperFormKwargsMixin, UpdateView):
    model = CitesDocument
    form_class = CitesDocumentForm
    template_name = "form.html"
    extra_context = {"title": "Modifica documento CITES"}
    success_url = reverse_lazy("registry:document_list")


class MarkingDelete(KeeperEditMixin, DeleteView):
    model = Marking
    keeper_field = "specimen__keeper"
    template_name = "confirm_delete.html"

    def get_success_url(self):
        return reverse("registry:specimen_detail", args=[self.object.specimen_id])


# --------------------------------------------------------------------------- register

class RegisterView(KeeperRequiredMixin, ListView):
    model = RegisterEntry
    template_name = "registry/register.html"
    paginate_by = 100

    def get_queryset(self):
        qs = super().get_queryset().select_related("species", "carico_ref")
        self.register_type = self.request.GET.get("type", "EA")
        year = self.request.GET.get("year")
        qs = qs.filter(register_type=self.register_type)
        if year:
            qs = qs.filter(event_date__year=year)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["register_type"] = self.register_type
        ctx["types"] = RegisterEntry.RegisterType.choices
        ctx["years"] = (RegisterEntry.objects.filter(keeper=self.request.keeper)
                        .dates("event_date", "year", order="DESC"))
        return ctx


def register_export(request, fmt):
    if request.keeper is None:
        return redirect("accounts:keeper_create")
    register_type = request.GET.get("type", "EA")
    entries = RegisterEntry.objects.filter(keeper=request.keeper, register_type=register_type).select_related(
        "species", "carico_ref")
    if request.GET.get("year"):
        entries = entries.filter(event_date__year=request.GET["year"])
    if fmt == "xlsx":
        data = exports.register_xlsx(request.keeper, register_type, entries)
        resp = HttpResponse(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="registro_{register_type}.xlsx"'
        return resp
    data = exports.register_pdf(request.keeper, register_type, entries)
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="registro_{register_type}.pdf"'
    return resp


def register_correction(request, pk):
    """Append a rettifica entry (the register is never edited)."""
    _keeper_guard(request)
    entry = get_object_or_404(RegisterEntry, pk=pk, keeper=request.keeper)
    if request.method == "POST":
        note = request.POST.get("notes", "").strip()
        qty = int(request.POST.get("quantity") or entry.quantity)
        RegisterEntry.objects.create(
            keeper=entry.keeper, register_type=entry.register_type,
            direction=RegisterEntry.Direction.OUT if entry.direction == "carico" else RegisterEntry.Direction.IN,
            cause=RegisterEntry.Cause.CORRECTION, event_date=entry.event_date, species=entry.species,
            specimen=entry.specimen, quantity=qty, description=entry.description, marking=entry.marking,
            document=entry.document, counterparty=entry.counterparty, corrects=entry,
            notes=f"Rettifica reg. n. {entry.number}: {note}"[:255], created_by=request.user,
        )
        messages.success(request, f"Rettifica della registrazione n. {entry.number} inserita.")
        return redirect(f"{reverse('registry:register')}?type={entry.register_type}")
    return render(request, "registry/register_correction.html", {"entry": entry})
