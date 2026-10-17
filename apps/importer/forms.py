from django import forms

from apps.declarations.models import Declaration, FeeType
from apps.registry.models import CitesDocument, Specimen
from apps.species.models import Species

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultiFileInput(attrs={"multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return [single(data, initial)] if data else []


class UploadForm(forms.Form):
    files = MultiFileField(required=False, label="File (PDF, immagini, XLSX)")
    archive = forms.FileField(required=False, label="Oppure un archivio ZIP (mantiene le cartelle per anno)")
    label = forms.CharField(required=False, label="Descrizione import")


ACTIONS = [
    ("birth", "Denuncia di nascita → crea esemplari nati"),
    ("death", "Comunicazione di decesso → scarica esemplari"),
    ("document", "Risposta ufficio / certificato → documento CITES"),
    ("payment", "Ricevuta di pagamento"),
    ("archive", "Archivia solo (es. documento d'identità)"),
    ("skip", "Ignora"),
]

ACTION_BY_KIND = {"SCT1A": "birth", "SCT1B": "birth", "SCT5": "death", "REPLY": "document", "CERT": "document",
                  "SCT3": "archive", "PAYMENT": "payment", "ID": "archive", "OTHER": "archive", "SHEET": "skip"}


class ReviewForm(forms.Form):
    action = forms.ChoiceField(choices=ACTIONS, label="Azione")
    species = forms.ModelChoiceField(Species.objects.all(), required=False, label="Specie")
    quantity = forms.IntegerField(min_value=1, required=False, label="Numero esemplari")
    event_date = forms.DateField(required=False, widget=DATE, label="Data evento (nascita / decesso)")
    signed_on = forms.DateField(required=False, widget=DATE, label="Data denuncia (firma/invio)")
    breeding_group = forms.CharField(required=False, label="Gruppo riproduttore / riferimenti")
    specimen = forms.ModelChoiceField(Specimen.objects.none(), required=False, label="Esemplare / lotto deceduto")
    protocol_number = forms.CharField(required=False, label="Protocollo ufficio (se noto)")
    protocol_date = forms.DateField(required=False, widget=DATE, label="Data protocollo")
    doc_type = forms.ChoiceField(choices=CitesDocument.DocType.choices, required=False, label="Tipo documento")
    number = forms.CharField(required=False, label="Numero / protocollo / riferimento")
    issued_on = forms.DateField(required=False, widget=DATE, label="Data documento")
    specimens = forms.ModelMultipleChoiceField(Specimen.objects.none(), required=False, label="Esemplari collegati",
                                               widget=forms.SelectMultiple(attrs={"size": 6}))
    link_declaration = forms.ModelChoiceField(Declaration.objects.none(), required=False,
                                              label="Collega alla denuncia")
    amount = forms.DecimalField(required=False, max_digits=8, decimal_places=2, label="Importo €")
    paid_on = forms.DateField(required=False, widget=DATE, label="Data pagamento")
    fee_type = forms.ModelChoiceField(FeeType.objects.all(), required=False, label="Codice diritto")
    notes = forms.CharField(required=False, label="Note / causale")

    REQUIRED = {
        "birth": ["species", "quantity", "event_date"],
        "death": ["species", "quantity", "event_date"],
        "document": ["doc_type", "number"],
        "payment": ["amount", "paid_on"],
    }

    def __init__(self, *args, keeper=None, **kwargs):
        super().__init__(*args, **kwargs)
        specimens = Specimen.objects.filter(keeper=keeper).select_related("species")
        self.fields["specimen"].queryset = specimens.filter(status=Specimen.Status.ALIVE)
        self.fields["specimens"].queryset = specimens
        self.fields["link_declaration"].queryset = Declaration.objects.filter(keeper=keeper)

    def clean(self):
        cd = super().clean()
        for name in self.REQUIRED.get(cd.get("action"), []):
            if not cd.get(name):
                self.add_error(name, "Obbligatorio per questa azione.")
        sp = cd.get("specimen")
        if cd.get("action") == "death" and sp and (cd.get("quantity") or 1) > sp.quantity:
            self.add_error("quantity", f"Il lotto contiene solo {sp.quantity} esemplari.")
        return cd


class SheetForm(forms.Form):
    file = forms.FileField(label="File XLSX esemplari")
