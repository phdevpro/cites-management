import hashlib

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Keeper
from apps.vault.fields import EncryptedCharField, EncryptedJSONField, EncryptedTextField
from apps.vault.storage import EncryptedFileField

from .parse import KINDS


def file_sha256(django_file, keeper=None) -> str:
    """Duplicate-detection fingerprint. For encrypted keepers it is keyed with the keeper's data key,
    so the stored value cannot be used to confirm that someone holds a known document."""
    django_file.seek(0)
    data = b"".join(django_file.chunks())
    django_file.seek(0)
    if keeper is not None and keeper.key_id:
        from apps.vault import crypto
        from apps.vault.context import ring

        return crypto.keyed_hash(ring().dek(keeper.key_id), data)
    return hashlib.sha256(data).hexdigest()


class ImportBatch(models.Model):
    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="import_batches")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    label = EncryptedCharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.label or f"Import {self.created_at:%d/%m/%Y %H:%M}"


class ImportedFile(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Da analizzare")
        PARSED = "parsed", _("Da verificare")
        DONE = "done", _("Registrato")
        ARCHIVED = "archived", _("Solo archiviato")
        SKIPPED = "skipped", _("Ignorato")
        ERROR = "error", _("Errore")

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="files")
    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="imported_files")
    file = EncryptedFileField(upload_to="imports/")
    original_name = EncryptedCharField(max_length=255)
    original_path = EncryptedCharField(max_length=500, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    detected_kind = models.CharField(_("tipo rilevato"), max_length=8, choices=list(KINDS.items()), default="OTHER")
    confidence = models.FloatField(default=0)
    method = models.CharField(max_length=10, blank=True)
    text = EncryptedTextField(blank=True)
    parsed = EncryptedJSONField(default=dict, blank=True)
    error = EncryptedTextField(blank=True)
    year_hint = models.PositiveIntegerField(null=True, blank=True)
    declaration = models.ForeignKey(
        "declarations.Declaration", on_delete=models.SET_NULL, null=True, blank=True, related_name="imported_files"
    )
    cites_document = models.ForeignKey(
        "registry.CitesDocument", on_delete=models.SET_NULL, null=True, blank=True, related_name="imported_files"
    )

    class Meta:
        ordering = ["year_hint", "pk"]
        constraints = [models.UniqueConstraint(fields=["keeper", "sha256"], name="unique_import_per_keeper")]

    def __str__(self):
        return self.original_name

    @property
    def is_pdf(self):
        return self.original_name.lower().endswith(".pdf")

    @property
    def is_image(self):
        return self.original_name.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png")
