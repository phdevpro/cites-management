from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from apps.accounts.models import DetentionSite, Keeper
from apps.species.models import Species
from apps.vault.fields import EncryptedCharField, EncryptedDateField, EncryptedEmailField, EncryptedTextField
from apps.vault.storage import EncryptedFileField, EncryptedImageField


class Counterparty(models.Model):
    """Cedente / cessionario (rubrica del detentore)."""

    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="counterparties")
    first_name = EncryptedCharField(_("nome"), max_length=100, blank=True)
    last_name = EncryptedCharField(_("cognome"), max_length=100, blank=True)
    company_name = EncryptedCharField(_("ragione sociale / allevamento"), max_length=200, blank=True)
    fiscal_code = EncryptedCharField(_("codice fiscale / P.IVA"), max_length=16, blank=True)
    birth_place = EncryptedCharField(_("luogo di nascita"), max_length=100, blank=True)
    birth_date = EncryptedDateField(_("data di nascita"), null=True, blank=True)
    address = EncryptedCharField(_("via e civico"), max_length=200, blank=True)
    postal_code = EncryptedCharField(_("CAP"), max_length=5, blank=True)
    city = EncryptedCharField(_("comune"), max_length=100, blank=True)
    province = EncryptedCharField(_("provincia"), max_length=2, blank=True)
    phone = EncryptedCharField(_("telefono"), max_length=50, blank=True)
    email = EncryptedEmailField(_("email"), blank=True)
    id_doc_number = EncryptedCharField(_("documento identità n."), max_length=50, blank=True)
    id_doc_file = EncryptedFileField(_("copia documento"), upload_to="counterparties/id/", blank=True)
    breeding_type = models.CharField(
        _("tipologia allevamento"), max_length=20, blank=True,
        choices=[("amatoriale", "Amatoriale"), ("commerciale", "Commerciale"), ("zoo", "Giardino zoologico"),
                 ("recupero", "Centro recupero"), ("altro", "Altro")],
    )
    notes = EncryptedTextField(_("note"), blank=True)

    class Meta:
        ordering = ["pk"]  # names are encrypted: sort in Python
        verbose_name = _("controparte")
        verbose_name_plural = _("controparti")

    def __str__(self):
        return self.company_name or f"{self.first_name} {self.last_name}".strip() or f"#{self.pk}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.company_name

    @property
    def full_address(self):
        line = ", ".join(p for p in [self.address, " ".join(x for x in [self.postal_code, self.city] if x)] if p)
        return f"{line} ({self.province})" if self.province else line


class Specimen(models.Model):
    """Esemplare o lotto di esemplari (es. 9 neonati Testudo non ancora marcati)."""

    class Sex(models.TextChoices):
        MALE = "M", _("Maschio")
        FEMALE = "F", _("Femmina")
        UNKNOWN = "I", _("Indeterminato")

    class Origin(models.TextChoices):
        BORN_HERE = "born", _("Nato in allevamento")
        ACQUIRED = "acquired", _("Acquisito (cessione)")
        IMPORTED = "imported", _("Importato")
        PRE_EXISTING = "pre", _("Detenuto da prima / denunciato")
        OTHER = "other", _("Altro")

    class SourceCode(models.TextChoices):
        C = "C", "C – Riprodotto in cattività"
        F = "F", "F – Nato in cattività (F1+)"
        W = "W", "W – Prelevato in natura"
        R = "R", "R – Ranching"
        D = "D", "D – Allevamento registrato (All. I)"
        I = "I", "I – Confiscato/sequestrato"
        U = "U", "U – Sconosciuta"
        O = "O", "O – Pre-convenzione"

    class Status(models.TextChoices):
        ALIVE = "alive", _("Vivo / detenuto")
        DEAD = "dead", _("Deceduto")
        TRANSFERRED = "transferred", _("Ceduto")
        LOST = "lost", _("Smarrito")
        ESCAPED = "escaped", _("Fuggito")
        STOLEN = "stolen", _("Rubato")

    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="specimens")
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name="specimens", verbose_name=_("specie"))
    site = models.ForeignKey(DetentionSite, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("sito"))
    name = EncryptedCharField(_("nome / identificativo interno"), max_length=100, blank=True)
    quantity = models.PositiveIntegerField(_("numero esemplari"), default=1)
    sex = models.CharField(_("sesso"), max_length=1, choices=Sex.choices, default=Sex.UNKNOWN)
    birth_date = models.DateField(_("data di nascita"), null=True, blank=True)
    birth_date_approx = models.BooleanField(_("data approssimata (solo anno)"), default=False)
    origin = models.CharField(_("provenienza"), max_length=10, choices=Origin.choices, default=Origin.PRE_EXISTING)
    source_code = models.CharField(_("codice origine"), max_length=1, choices=SourceCode.choices, default="C")
    status = models.CharField(_("stato"), max_length=12, choices=Status.choices, default=Status.ALIVE)
    status_date = models.DateField(_("data variazione stato"), null=True, blank=True)
    father = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children_as_father",
        verbose_name=_("padre"), limit_choices_to={"sex": "M"},
    )
    mother = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children_as_mother",
        verbose_name=_("madre"), limit_choices_to={"sex": "F"},
    )
    breeding_group = EncryptedCharField(
        _("gruppo riproduttore"), max_length=255, blank=True,
        help_text=_("Se i genitori non sono individuabili univocamente (es. 'PROT 123 DEL 1999')."),
    )
    split_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="splits",
        verbose_name=_("derivato dal lotto"),
    )
    acquired_from = models.ForeignKey(
        Counterparty, on_delete=models.SET_NULL, null=True, blank=True, related_name="specimens_sold",
        verbose_name=_("acquisito da"),
    )
    acquired_on = models.DateField(_("data acquisizione"), null=True, blank=True)
    transferred_to = models.ForeignKey(
        Counterparty, on_delete=models.SET_NULL, null=True, blank=True, related_name="specimens_bought",
        verbose_name=_("ceduto a"),
    )
    cause_of_death = EncryptedCharField(_("causa decesso"), max_length=255, blank=True)
    photo = EncryptedImageField(_("foto"), upload_to="specimens/", blank=True)
    notes = EncryptedTextField(_("note"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["species__scientific_name", "birth_date", "pk"]
        verbose_name = _("esemplare")
        verbose_name_plural = _("esemplari")

    def __str__(self):
        label = self.name or f"#{self.pk}"
        qty = f" ×{self.quantity}" if self.quantity > 1 else ""
        return f"{self.species.scientific_name} {label}{qty}"

    def get_absolute_url(self):
        return reverse("registry:specimen_detail", args=[self.pk])

    def clean(self):
        if self.father_id and self.father_id == self.pk:
            raise ValidationError(_("Un esemplare non può essere padre di sé stesso."))
        if self.mother_id and self.mother_id == self.pk:
            raise ValidationError(_("Un esemplare non può essere madre di sé stesso."))

    @property
    def is_alive(self):
        return self.status == self.Status.ALIVE

    @property
    def is_lot(self):
        return self.quantity > 1

    @property
    def markings_label(self):
        marks = list(self.markings.all())
        if not marks:
            return ""
        return "; ".join(m.label for m in marks)

    @property
    def marking_types_label(self):
        return ", ".join(sorted({m.get_kind_display() for m in self.markings.all()}))

    @property
    def marking_codes_label(self):
        return ", ".join(m.code for m in self.markings.all() if m.code)

    @property
    def current_document(self):
        return self.cites_documents.order_by("-issued_on", "-pk").first()

    @property
    def offspring(self):
        return Specimen.objects.filter(models.Q(father=self) | models.Q(mother=self))

    @property
    def needs_microchip(self):
        """Testudo: nano microchip within first year of life."""
        return (
            self.is_alive and self.species.is_testudo and not self.markings.exists() and self.birth_date is not None
        )


class Marking(models.Model):
    class Kind(models.TextChoices):
        MICROCHIP = "microchip", _("Microchip")
        RING = "ring", _("Anello inamovibile")
        PHOTO = "photo", _("Foto-identificazione")
        OTHER = "other", _("Altro")

    specimen = models.ForeignKey(Specimen, on_delete=models.CASCADE, related_name="markings")
    kind = models.CharField(_("tipo marcatura"), max_length=10, choices=Kind.choices, default=Kind.MICROCHIP)
    code = EncryptedCharField(_("estremi / codice"), max_length=100, blank=True)
    manufacturer = EncryptedCharField(_("produttore"), max_length=100, blank=True)
    applied_on = models.DateField(_("data applicazione"), null=True, blank=True)
    applied_by = EncryptedCharField(_("applicato da (veterinario)"), max_length=200, blank=True)
    photo = EncryptedImageField(_("foto"), upload_to="markings/", blank=True)

    class Meta:
        verbose_name = _("marcatura")
        verbose_name_plural = _("marcature")

    def __str__(self):
        return self.label

    @property
    def label(self):
        return f"{self.get_kind_display()} {self.code}".strip()


class CitesDocument(models.Model):
    class DocType(models.TextChoices):
        CERT_ART10 = "art10", _("Certificato art. 10 (CIC)")
        CERT_MOVE = "art9", _("Certificato spostamento art. 9.2")
        EU_CERT = "eucert", _("Certificato comunitario")
        IMPORT_LICENSE = "import", _("Licenza di importazione")
        BIRTH_PROTOCOL = "dn", _("Protocollo denuncia di nascita")
        DEATH_PROTOCOL = "dd", _("Protocollo comunicazione decesso")
        OLD_DECLARATION = "old", _("Denuncia/protocollo storico")
        OTHER = "other", _("Altro")

    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="cites_documents")
    doc_type = models.CharField(_("tipo"), max_length=10, choices=DocType.choices)
    number = EncryptedCharField(_("numero / protocollo"), max_length=100, help_text="es. IT/CE/2024/XX/00001, 1234 10/100-1")
    issued_on = models.DateField(_("data"), null=True, blank=True)
    issuer = EncryptedCharField(_("rilasciato da (ufficio/Stato)"), max_length=200, blank=True)
    file = EncryptedFileField(_("file"), upload_to="cites_documents/", blank=True)
    specimens = models.ManyToManyField(Specimen, related_name="cites_documents", blank=True, verbose_name=_("esemplari"))
    returned_on = models.DateField(
        _("restituito il"), null=True, blank=True, help_text=_("Certificato restituito (es. con SCT5).")
    )
    notes = EncryptedTextField(_("note"), blank=True)

    class Meta:
        ordering = ["-issued_on", "-pk"]
        verbose_name = _("documento CITES")
        verbose_name_plural = _("documenti CITES")

    def __str__(self):
        return self.form_label

    @property
    def form_label(self):
        """Representation used inside the official forms (e.g. '1234 10/100-1 - 31/10/2024')."""
        date = self.issued_on.strftime("%d/%m/%Y") if self.issued_on else ""
        return " - ".join(p for p in [self.number, date] if p)


class RegisterEntry(models.Model):
    """Registro di carico e scarico (D.M. 8/1/2002). Append-only: never updated or deleted."""

    class RegisterType(models.TextChoices):
        EA = "EA", _("EA – Animali All. A")
        EB = "EB", _("EB – Animali All. B")

    class Direction(models.TextChoices):
        IN = "carico", _("Carico")
        OUT = "scarico", _("Scarico")

    class Cause(models.TextChoices):
        INITIAL = "iniziale", _("Consistenza iniziale")
        BIRTH = "nascita", _("Nascita in cattività")
        PURCHASE = "acquisto", _("Acquisto / acquisizione")
        IMPORT = "import", _("Importazione")
        SALE = "vendita", _("Vendita")
        TRANSFER = "cessione", _("Cessione gratuita")
        DEATH = "decesso", _("Decesso")
        LOSS = "smarrimento", _("Smarrimento / fuga / furto")
        CORRECTION = "rettifica", _("Rettifica")
        OTHER = "altro", _("Altro")

    keeper = models.ForeignKey(Keeper, on_delete=models.PROTECT, related_name="register_entries")
    register_type = models.CharField(_("registro"), max_length=2, choices=RegisterType.choices)
    number = models.PositiveIntegerField(_("n. progressivo"))
    direction = models.CharField(_("movimento"), max_length=8, choices=Direction.choices)
    cause = models.CharField(_("causale"), max_length=12, choices=Cause.choices)
    recorded_at = models.DateTimeField(_("data registrazione"), default=timezone.now)
    event_date = models.DateField(_("data evento"))
    species = models.ForeignKey(Species, on_delete=models.PROTECT)
    specimen = models.ForeignKey(Specimen, on_delete=models.SET_NULL, null=True, blank=True, related_name="register_entries")
    quantity = models.PositiveIntegerField(_("quantità"), default=1)
    description = models.CharField(_("descrizione"), max_length=255, default="esemplare vivo")
    marking = EncryptedCharField(_("marcatura"), max_length=255, blank=True)
    document = EncryptedCharField(_("documento CITES"), max_length=255, blank=True)
    counterparty = EncryptedCharField(_("provenienza / destinazione"), max_length=255, blank=True)
    carico_ref = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="scarichi",
        verbose_name=_("riferimento carico"),
    )
    corrects = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrections",
        verbose_name=_("rettifica la registrazione"),
    )
    notes = EncryptedCharField(_("note"), max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["register_type", "number"]
        unique_together = [("keeper", "register_type", "number")]
        verbose_name = _("registrazione carico/scarico")
        verbose_name_plural = _("registro carico/scarico")

    def __str__(self):
        return f"{self.register_type} {self.number} {self.direction} {self.species} ×{self.quantity}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Il registro è immodificabile: registrare una rettifica.")
        with transaction.atomic():
            if not self.number:
                last = (
                    RegisterEntry.objects.select_for_update()
                    .filter(keeper=self.keeper, register_type=self.register_type)
                    .aggregate(m=Max("number"))["m"]
                )
                self.number = (last or 0) + 1
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Il registro è immodificabile: le registrazioni non possono essere cancellate.")

    @property
    def is_late(self):
        days = settings.CITES_DEADLINES["register_entry"]
        return (self.recorded_at.date() - self.event_date).days > days

    @classmethod
    def register_type_for(cls, species):
        return cls.RegisterType.EA if species.eu_annex == "A" else cls.RegisterType.EB
