from django import forms
from django.forms import formset_factory

from apps.registry.models import Counterparty, Marking, Specimen
from apps.species.models import Species

from .models import Attachment, Declaration, FeeType, Payment

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _alive(keeper):
    return Specimen.objects.filter(keeper=keeper, status=Specimen.Status.ALIVE).select_related("species")


class BirthForm(forms.Form):
    species = forms.ModelChoiceField(Species.objects.filter(eu_annex__in=["A", "B"]), label="Specie")
    birth_date = forms.DateField(widget=DATE, label="Data di nascita / schiusa")
    father = forms.ModelChoiceField(Specimen.objects.none(), required=False, label="Padre")
    mother = forms.ModelChoiceField(Specimen.objects.none(), required=False, label="Madre")
    breeding_group = forms.CharField(
        required=False, label="Gruppo riproduttore / riferimenti genitori",
        help_text="Se i genitori non sono individuabili: es. 'PROT 123 DEL 1999'",
    )

    def __init__(self, *args, keeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        alive = _alive(keeper)
        self.fields["father"].queryset = alive.filter(sex="M")
        self.fields["mother"].queryset = alive.filter(sex="F")
        last = next((s for s in Specimen.objects.filter(keeper=keeper, origin="born").order_by("-pk")[:50]
                     if s.breeding_group), None)
        if last and not self.is_bound:
            self.fields["breeding_group"].initial = last.breeding_group
            self.fields["species"].initial = last.species_id


class NewbornRowForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, initial=1, label="N.")
    sex = forms.ChoiceField(choices=Specimen.Sex.choices, initial="I", label="Sesso")
    name = forms.CharField(required=False, label="Nome")
    marking_kind = forms.ChoiceField(choices=[("", "— nessuna —")] + list(Marking.Kind.choices), required=False,
                                     label="Marcatura")
    marking_code = forms.CharField(required=False, label="Estremi")

    def clean(self):
        cd = super().clean()
        if cd.get("marking_kind") and cd.get("quantity", 1) > 1:
            raise forms.ValidationError("Un lotto con più esemplari non può avere un'unica marcatura.")
        return cd


NewbornFormSet = formset_factory(NewbornRowForm, extra=0, min_num=1, validate_min=True, max_num=50)


class DeathForm(forms.Form):
    specimen = forms.ModelChoiceField(Specimen.objects.none(), label="Esemplare / lotto")
    quantity = forms.IntegerField(min_value=1, initial=1, label="Numero deceduti")
    death_date = forms.DateField(widget=DATE, label="Data decesso")
    cause = forms.CharField(required=False, label="Causa (facoltativa)")

    def __init__(self, *args, keeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["specimen"].queryset = _alive(keeper)

    def clean(self):
        cd = super().clean()
        sp, qty = cd.get("specimen"), cd.get("quantity")
        if sp and qty and qty > sp.quantity:
            raise forms.ValidationError(f"Il lotto contiene solo {sp.quantity} esemplari.")
        return cd


class LossForm(DeathForm):
    status = forms.ChoiceField(
        choices=[(Specimen.Status.LOST, "Smarrimento"), (Specimen.Status.ESCAPED, "Fuga"),
                 (Specimen.Status.STOLEN, "Furto")], label="Evento",
    )
    circumstances = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Circostanze",
                                    help_text="In caso di furto allegare copia della denuncia alle autorità.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["cause"]
        self.fields["death_date"].label = "Data evento"
        self.fields["quantity"].label = "Numero esemplari"


class TransferForm(forms.Form):
    counterparty = forms.ModelChoiceField(Counterparty.objects.none(), label="Cessionario (destinatario)")
    transfer_date = forms.DateField(widget=DATE, label="Data cessione prevista")
    is_sale = forms.BooleanField(required=False, initial=True, label="Vendita (a titolo oneroso)")
    specimens = forms.ModelMultipleChoiceField(
        Specimen.objects.none(), widget=forms.CheckboxSelectMultiple, label="Esemplari"
    )

    def __init__(self, *args, keeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["counterparty"].queryset = Counterparty.objects.filter(keeper=keeper)
        self.fields["specimens"].queryset = _alive(keeper)
        self.keeper = keeper

    def quantities(self, data):
        """Per-specimen quantity inputs named qty_<pk>."""
        out = {}
        for sp in self.cleaned_data.get("specimens", []):
            try:
                out[sp.pk] = max(1, min(int(data.get(f"qty_{sp.pk}", 1)), sp.quantity))
            except ValueError:
                out[sp.pk] = 1
        return out


class CompleteTransferForm(forms.Form):
    completed_on = forms.DateField(widget=DATE, label="Data consegna esemplari")
    certificate_number = forms.CharField(required=False, label="N. certificato spostamento",
                                         help_text="es. IT/CE/2024/XX/00001")
    certificate_date = forms.DateField(required=False, widget=DATE, label="Data certificato")
    certificate_file = forms.FileField(required=False, label="Copia certificato")


class SentForm(forms.Form):
    sent_on = forms.DateField(widget=DATE, label="Data invio")
    channel = forms.ChoiceField(choices=Declaration.Channel.choices, label="Modalità")


class ProtocolForm(forms.Form):
    protocol_number = forms.CharField(label="Protocollo / riferimento ufficio", help_text="es. 1234 (10.100-1)")
    protocol_date = forms.DateField(required=False, widget=DATE, label="Data")
    reply_file = forms.FileField(required=False, label="Risposta / ricevuta ufficio")


class DeclarationMetaForm(forms.ModelForm):
    class Meta:
        model = Declaration
        fields = ["office", "event_date", "deadline", "place", "signed_on", "notes"]
        widgets = {"event_date": DATE, "deadline": DATE, "signed_on": DATE, "notes": forms.Textarea(attrs={"rows": 2})}


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["kind", "file", "description"]


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["fee_type", "amount", "paid_on", "reference", "description", "receipt", "declaration"]
        widgets = {"paid_on": DATE}

    def __init__(self, *args, keeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["declaration"].queryset = Declaration.objects.filter(keeper=keeper)
        self.fields["fee_type"].queryset = FeeType.objects.all()


class PdfOptionsForm(forms.Form):
    """Asked before generating when the declarant's signature or identity document is missing."""

    include_signature = forms.BooleanField(required=False, initial=True, label="Apponi la firma del dichiarante")
    signature = forms.ImageField(required=False, label="Carica la firma",
                                 help_text="PNG o JPG della firma su sfondo bianco: lo sfondo viene reso trasparente. "
                                           "Viene salvata cifrata nel profilo e riusata.")
    include_id = forms.BooleanField(required=False, initial=True, label="Allega il documento d'identità in coda al PDF")
    id_doc = forms.FileField(required=False, label="Carica il documento d'identità",
                             help_text="PDF o immagine (fronte/retro). Salvato cifrato nel profilo e riusato.")

    def __init__(self, *args, keeper=None, can_upload=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.keeper = keeper
        if not can_upload:
            del self.fields["signature"]
            del self.fields["id_doc"]

    def clean_signature(self):
        from apps.accounts.forms import clean_signature_upload

        return clean_signature_upload(self.cleaned_data.get("signature"))

    def clean_id_doc(self):
        from apps.accounts.forms import clean_id_document_upload

        return clean_id_document_upload(self.cleaned_data.get("id_doc"))

    def clean(self):
        cd = super().clean()
        if cd.get("include_signature") and not (cd.get("signature") or self.keeper.signature):
            self.add_error("signature", "Carica la firma oppure togli la spunta per generare senza.")
        if cd.get("include_id") and not (cd.get("id_doc") or self.keeper.id_doc_file):
            self.add_error("id_doc", "Carica il documento oppure togli la spunta per generare senza.")
        return cd
