from django import forms

from apps.species.models import Species

from .models import CitesDocument, Counterparty, Marking, Specimen

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class KeeperScopedForm(forms.ModelForm):
    """Restrict FK querysets to the current keeper."""

    keeper_scoped = {}

    def __init__(self, *args, keeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.keeper = keeper
        for name, model in self.keeper_scoped.items():
            if name in self.fields:
                self.fields[name].queryset = model.objects.filter(keeper=keeper)


class SpecimenForm(KeeperScopedForm):
    keeper_scoped = {"father": Specimen, "mother": Specimen, "acquired_from": Counterparty}

    class Meta:
        model = Specimen
        fields = ["species", "name", "quantity", "sex", "birth_date", "birth_date_approx", "origin", "source_code",
                  "father", "mother", "breeding_group", "acquired_from", "acquired_on", "site", "photo", "notes"]
        widgets = {"birth_date": DATE, "acquired_on": DATE, "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["father"].queryset = self.fields["father"].queryset.filter(sex="M")
        self.fields["mother"].queryset = self.fields["mother"].queryset.filter(sex="F")
        self.fields["site"].queryset = self.keeper.sites.all() if self.keeper else self.fields["site"].queryset.none()


class AcquisitionForm(forms.Form):
    """Add animals already held (consistenza iniziale) or bought."""

    species = forms.ModelChoiceField(Species.objects.all(), label="Specie")
    quantity = forms.IntegerField(min_value=1, initial=1, label="Numero esemplari")
    sex = forms.ChoiceField(choices=Specimen.Sex.choices, initial="I", label="Sesso")
    name = forms.CharField(required=False, label="Nome / identificativo")
    birth_date = forms.DateField(required=False, widget=DATE, label="Data di nascita")
    origin = forms.ChoiceField(choices=Specimen.Origin.choices, initial="pre", label="Provenienza")
    acquired_on = forms.DateField(widget=DATE, label="Data acquisizione / inizio detenzione")
    counterparty = forms.ModelChoiceField(Counterparty.objects.none(), required=False, label="Acquisito da")
    marking_kind = forms.ChoiceField(choices=[("", "—")] + list(Marking.Kind.choices), required=False,
                                     label="Tipo marcatura")
    marking_code = forms.CharField(required=False, label="Estremi marcatura")
    doc_type = forms.ChoiceField(choices=[("", "—")] + list(CitesDocument.DocType.choices), required=False,
                                 label="Documento CITES")
    doc_number = forms.CharField(required=False, label="Numero documento", help_text="es. IT/CE/2024/XX/00001")
    doc_date = forms.DateField(required=False, widget=DATE, label="Data documento")

    def __init__(self, *args, keeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counterparty"].queryset = Counterparty.objects.filter(keeper=keeper)


class MarkingForm(forms.ModelForm):
    notify = forms.BooleanField(required=False, initial=True, label="Prepara comunicazione marcatura al Servizio CITES")

    class Meta:
        model = Marking
        fields = ["kind", "code", "manufacturer", "applied_on", "applied_by"]
        widgets = {"applied_on": DATE}


class CounterpartyForm(forms.ModelForm):
    class Meta:
        model = Counterparty
        exclude = ["keeper"]
        widgets = {"birth_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class CitesDocumentForm(KeeperScopedForm):
    keeper_scoped = {"specimens": Specimen}

    class Meta:
        model = CitesDocument
        fields = ["doc_type", "number", "issued_on", "issuer", "file", "specimens", "returned_on", "notes"]
        widgets = {"issued_on": DATE, "returned_on": DATE, "specimens": forms.SelectMultiple(attrs={"size": 8}),
                   "notes": forms.Textarea(attrs={"rows": 2})}


class SplitForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, label="Esemplari da separare")
    name = forms.CharField(required=False, label="Nome nuovo lotto/esemplare")
