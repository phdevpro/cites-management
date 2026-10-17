import hashlib

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Keeper

from .parse import KINDS


def file_sha256(django_file) -> str:
    h = hashlib.sha256()
    django_file.seek(0)
    for chunk in django_file.chunks():
        h.update(chunk)
    django_file.seek(0)
    return h.hexdigest()


class ImportBatch(models.Model):
    keeper = models.ForeignKey(Keeper, on_delete=models.CASCADE, related_name="import_batches")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    label = models.CharField(max_length=200, blank=True)

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
    file = models.FileField(upload_to="imports/")
    original_name = models.CharField(max_length=255)
    original_path = models.CharField(max_length=500, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    detected_kind = models.CharField(_("tipo rilevato"), max_length=8, choices=list(KINDS.items()), default="OTHER")
    confidence = models.FloatField(default=0)
    method = models.CharField(max_length=10, blank=True)
    text = models.TextField(blank=True)
    parsed = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    year_hint = models.PositiveIntegerField(null=True, blank=True)
    declaration = models.ForeignKey(
        "declarations.Declaration", on_delete=models.SET_NULL, null=True, blank=True, related_name="imported_files"
    )
    cites_document = models.ForeignKey(
        "registry.CitesDocument", on_delete=models.SET_NULL, null=True, blank=True, related_name="imported_files"
    )

    class Meta:
        ordering = ["year_hint", "original_path", "original_name"]
        constraints = [models.UniqueConstraint(fields=["keeper", "sha256"], name="unique_import_per_keeper")]

    def __str__(self):
        return self.original_name

    @property
    def is_pdf(self):
        return self.original_name.lower().endswith(".pdf")

    @property
    def is_image(self):
        return self.original_name.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png")
