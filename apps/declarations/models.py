from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from apps.accounts.models import CitesOffice, Keeper
from apps.registry.models import CitesDocument, Counterparty, Specimen
from apps.vault.fields import EncryptedCharField, EncryptedJSONField, EncryptedTextField
from apps.vault.storage import EncryptedFileField


class Declaration(models.Model):
    class Kind(models.TextChoices):
        BIRTH_A = "SCT1A", _("Denuncia di nascita – All. A (SCT1/A)")
        BIRTH_B = "SCT1B", _("Denuncia di nascita – All. B (SCT1/B)")
        DEATH = "SCT5", _("Comunicazione di decesso (SCT5)")
        TRANSFER = "SCT3", _("Cessione / spostamento All. A – richiesta cert. art. 9.2 (SCT3)")
        SALE_B = "CESSB", _("Dichiarazione di cessione – All. B")
        LOSS = "LOSS", _("Comunicazione smarrimento / fuga / furto")
        SITE_CHANGE = "SITE", _("Comunicazione cambio luogo di detenzione")
        MARKING = "MARK", _("Comunicazione marcatura")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Bozza")
        GENERATED = "generated", _("PDF generato")
        SENT = "sent", _("Inviata")
        PROTOCOLLED = "protocolled", _("Protocollata dall'ufficio")
        CLOSED = "closed", _("Chiusa")

    class Channel(models.TextChoices):
        PEC = "pec", _("PEC")
        RACCOMANDATA = "racc", _("Raccomandata A/R")
        HAND = "hand", _("A mano")
        EMAIL = "email", _("Email")
        FAX = "fax", _("Fax")

    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="declarations")
    kind = models.CharField(_("tipo"), max_length=6, choices=Kind.choices)
    status = models.CharField(_("stato"), max_length=12, choices=Status.choices, default=Status.DRAFT)
    office = models.ForeignKey(CitesOffice, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("ufficio CITES"))
    event_date = models.DateField(_("data evento"))
    deadline = models.DateField(_("scadenza"), null=True, blank=True)
    counterparty = models.ForeignKey(
        Counterparty, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("controparte")
    )
    place = EncryptedCharField(_("luogo firma"), max_length=100, blank=True)
    signed_on = models.DateField(_("data firma"), default=timezone.localdate)
    data = EncryptedJSONField(_("dati modulo"), default=dict, blank=True)
    pdf = EncryptedFileField(_("PDF generato"), upload_to="declarations/pdf/", blank=True)
    sent_on = models.DateField(_("inviata il"), null=True, blank=True)
    channel = models.CharField(_("canale"), max_length=6, choices=Channel.choices, blank=True)
    protocol_number = EncryptedCharField(_("protocollo ufficio"), max_length=100, blank=True)
    protocol_date = models.DateField(_("data protocollo"), null=True, blank=True)
    notes = EncryptedTextField(_("note"), blank=True)
    imported = models.BooleanField(_("importata da archivio"), default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-event_date", "-pk"]
        verbose_name = _("denuncia")
        verbose_name_plural = _("denunce")

    def __str__(self):
        return f"{self.kind} {self.event_date:%d/%m/%Y} – {self.total_quantity} es."

    def get_absolute_url(self):
        return reverse("declarations:detail", args=[self.pk])

    @property
    def total_quantity(self):
        return sum(i.quantity for i in self.items.all())

    @property
    def is_overdue(self):
        return (
            self.deadline is not None
            and self.status in (self.Status.DRAFT, self.Status.GENERATED)
            and timezone.localdate() > self.deadline
        )

    @property
    def days_left(self):
        if self.deadline is None:
            return None
        return (self.deadline - timezone.localdate()).days

    @property
    def has_pdf_form(self):
        return self.kind in PDF_KINDS

    def compute_deadline(self):
        days = settings.CITES_DEADLINES
        mapping = {self.Kind.BIRTH_A: days["birth"], self.Kind.BIRTH_B: days["birth"], self.Kind.DEATH: days["death"],
                   self.Kind.LOSS: days["death"], self.Kind.SITE_CHANGE: days["death"]}
        if self.kind in mapping:
            return self.event_date + timedelta(days=mapping[self.kind])
        return None

    def save(self, *args, **kwargs):
        if self.deadline is None and not self.imported:
            self.deadline = self.compute_deadline()
        super().save(*args, **kwargs)


PDF_KINDS = {k.value for k in Declaration.Kind}


class DeclarationItem(models.Model):
    declaration = models.ForeignKey(Declaration, on_delete=models.CASCADE, related_name="items")
    specimen = models.ForeignKey(Specimen, on_delete=models.PROTECT, related_name="declaration_items")
    quantity = models.PositiveIntegerField(_("quantità"), default=1)
    document = models.ForeignKey(
        CitesDocument, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("documento CITES di riferimento")
    )

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.specimen} ×{self.quantity}"


class Attachment(models.Model):
    """Documents linked to a declaration: office reply, certificate, ID copies, receipts, original imports."""

    class Kind(models.TextChoices):
        SIGNED = "signed", _("Denuncia firmata")
        REPLY = "reply", _("Risposta ufficio / protocollo")
        CERTIFICATE = "cert", _("Certificato")
        ID_COPY = "id", _("Copia documento identità")
        RECEIPT = "receipt", _("Ricevuta pagamento")
        ORIGINAL = "original", _("Originale importato")
        OTHER = "other", _("Altro")

    declaration = models.ForeignKey(Declaration, on_delete=models.CASCADE, related_name="attachments")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)
    file = EncryptedFileField(upload_to="declarations/attachments/")
    description = EncryptedCharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.description or self.file.name


class FeeType(models.Model):
    """Diritti speciali di prelievo (codici pratica IPAC, avviso MASE 10/10/2024)."""

    code = models.CharField(_("codice pratica"), max_length=10, unique=True)
    description = models.CharField(_("descrizione"), max_length=255)
    amount = models.DecimalField(_("importo €"), max_digits=8, decimal_places=2)

    class Meta:
        ordering = ["code"]
        verbose_name = _("tipo diritto")
        verbose_name_plural = _("tipi diritto")

    def __str__(self):
        return f"{self.code} – {self.description} (€ {self.amount})"


class Payment(models.Model):
    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="payments")
    fee_type = models.ForeignKey(FeeType, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("tipo diritto"))
    declaration = models.ForeignKey(
        Declaration, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments", verbose_name=_("denuncia")
    )
    amount = models.DecimalField(_("importo €"), max_digits=8, decimal_places=2)
    paid_on = models.DateField(_("data pagamento"))
    reference = EncryptedCharField(_("riferimento / CRO / IUV"), max_length=100, blank=True)
    description = EncryptedCharField(_("causale"), max_length=255, blank=True)
    receipt = EncryptedFileField(_("ricevuta"), upload_to="payments/", blank=True)

    class Meta:
        ordering = ["-paid_on"]
        verbose_name = _("pagamento")
        verbose_name_plural = _("pagamenti")

    def __str__(self):
        return f"{self.paid_on:%d/%m/%Y} € {self.amount} {self.description}"
