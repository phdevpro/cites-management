from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.vault.fields import EncryptedCharField, EncryptedDateField, EncryptedEmailField
from apps.vault.storage import EncryptedFileField

from .validators import validate_codice_fiscale


class CitesOffice(models.Model):
    """Servizio CITES territoriale / Nucleo Carabinieri CITES."""

    name = models.CharField(_("nome"), max_length=200, help_text="es. Nucleo CITES Trieste")
    city = models.CharField(_("città (per intestazione modulo)"), max_length=100)
    address = models.CharField(_("indirizzo"), max_length=255, blank=True)
    pec = models.EmailField(_("PEC"), blank=True)
    email = models.EmailField(_("email"), blank=True)
    phone = models.CharField(_("telefono"), max_length=50, blank=True)

    class Meta:
        ordering = ["city"]
        verbose_name = _("ufficio CITES")
        verbose_name_plural = _("uffici CITES")

    def __str__(self):
        return self.name


class Keeper(models.Model):
    """Detentore / allevamento. Tenant root: all data hangs off a keeper."""

    class IdDocType(models.TextChoices):
        CI = "CI", _("Carta d'identità")
        PAT = "PAT", _("Patente")
        PASS = "PASS", _("Passaporto")

    first_name = EncryptedCharField(_("nome"), max_length=100)
    last_name = EncryptedCharField(_("cognome"), max_length=100)
    company_name = EncryptedCharField(_("ragione sociale / nome allevamento"), max_length=200, blank=True)
    fiscal_code = EncryptedCharField(
        _("codice fiscale"), max_length=16, blank=True, validators=[validate_codice_fiscale]
    )
    birth_place = EncryptedCharField(_("luogo di nascita"), max_length=100, blank=True)
    birth_province = EncryptedCharField(_("provincia di nascita"), max_length=2, blank=True)
    birth_date = EncryptedDateField(_("data di nascita"), null=True, blank=True)
    address = EncryptedCharField(_("via e civico"), max_length=200, blank=True)
    postal_code = EncryptedCharField(_("CAP"), max_length=5, blank=True)
    city = EncryptedCharField(_("comune di residenza"), max_length=100, blank=True)
    province = EncryptedCharField(_("provincia"), max_length=2, blank=True)
    phone = EncryptedCharField(_("telefono"), max_length=50, blank=True)
    email = EncryptedEmailField(_("email"), blank=True)
    pec = EncryptedEmailField(_("PEC"), blank=True)
    id_doc_type = models.CharField(_("tipo documento"), max_length=4, choices=IdDocType.choices, default=IdDocType.CI)
    id_doc_number = EncryptedCharField(_("numero documento"), max_length=50, blank=True)
    id_doc_expiry = models.DateField(_("scadenza documento"), null=True, blank=True)
    id_doc_file = EncryptedFileField(_("copia documento"), upload_to="keepers/id/", blank=True)
    cites_office = models.ForeignKey(
        CitesOffice, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("ufficio CITES di riferimento")
    )
    sells_specimens = models.BooleanField(
        _("cede/vende esemplari"),
        default=False,
        help_text=_("Se sì, è obbligatorio il registro di carico e scarico (D.M. 8/1/2002)."),
    )
    ai_api_key = EncryptedCharField(
        _("chiave API Regolo.ai"), max_length=200, blank=True,
        help_text=_("Per la lettura automatica dei documenti importati. Salvata cifrata con la chiave del profilo."),
    )
    key_id = models.CharField(max_length=32, null=True, blank=True, editable=False, unique=True,
                              help_text="Id della chiave dati del profilo (la chiave non è mai salvata in chiaro).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]  # names are encrypted: sort in Python
        verbose_name = _("detentore")
        verbose_name_plural = _("detentori")

    def __str__(self):
        return self.company_name or self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def full_address(self):
        parts = [self.address, " ".join(p for p in [self.postal_code, self.city] if p)]
        line = ", ".join(p for p in parts if p)
        return f"{line} ({self.province})" if self.province else line

    @property
    def id_doc_label(self):
        return f"{self.id_doc_type} {self.id_doc_number}".strip() if self.id_doc_number else ""

    @property
    def default_site(self):
        return self.sites.filter(is_default=True).first() or self.sites.first()


class DetentionSite(models.Model):
    """Sito di detenzione / allevamento."""

    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="sites")
    name = EncryptedCharField(_("nome allevamento"), max_length=200, blank=True)
    address = EncryptedCharField(_("via e civico"), max_length=200)
    postal_code = EncryptedCharField(_("CAP"), max_length=5, blank=True)
    city = EncryptedCharField(_("comune"), max_length=100)
    province = EncryptedCharField(_("provincia"), max_length=2, blank=True)
    phone = EncryptedCharField(_("telefono/fax"), max_length=50, blank=True)
    is_default = models.BooleanField(_("predefinito"), default=True)
    art54_submitted_on = models.DateField(
        _("dichiarazione conformità art. 54 Reg. 865/2006 – data"), null=True, blank=True
    )
    art54_protocol = EncryptedCharField(_("art. 54 – protocollo"), max_length=100, blank=True)

    class Meta:
        verbose_name = _("sito di detenzione")
        verbose_name_plural = _("siti di detenzione")

    def __str__(self):
        return self.full_address

    @property
    def full_address(self):
        line = ", ".join(p for p in [self.address, " ".join(x for x in [self.postal_code, self.city] if x)] if p)
        return f"{line} ({self.province})" if self.province else line


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", _("Titolare")
        EDITOR = "editor", _("Collaboratore")
        VIEWER = "viewer", _("Sola lettura")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OWNER)
    wrapped_dek = models.BinaryField(null=True, blank=True, editable=False,
                                     help_text="Chiave dati del profilo sigillata con la chiave pubblica dell'utente.")

    class Meta:
        unique_together = [("user", "keeper")]

    def __str__(self):
        return f"{self.user} → {self.keeper} ({self.role})"

    @property
    def can_edit(self):
        return self.role in (self.Role.OWNER, self.Role.EDITOR)


class TermsAcceptance(models.Model):
    """Proof that a user accepted a version of the Terms and Privacy notice, including the specific
    approval of the onerous clauses (art. 1341-1342 c.c.). Kept for the life of the account."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="terms_acceptances")
    version = models.CharField(_("versione"), max_length=20)
    clauses = models.CharField(_("clausole approvate specificamente"), max_length=100, blank=True)
    accepted_at = models.DateTimeField(_("accettato il"), auto_now_add=True)
    ip_address = models.CharField(_("indirizzo IP"), max_length=45, blank=True)

    class Meta:
        ordering = ["-accepted_at"]
        unique_together = [("user", "version")]
        verbose_name = _("accettazione termini")
        verbose_name_plural = _("accettazioni termini")

    def __str__(self):
        return f"{self.user} – {self.version}"
