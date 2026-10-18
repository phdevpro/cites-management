"""Serve uploaded files only to members of the keeper that owns them (ID copies, certificates…)."""

import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404

from apps.vault.context import VaultLocked

# (app_label.Model, file field, lookup path to Keeper)
PROTECTED = [
    ("accounts.Keeper", "id_doc_file", ""),
    ("registry.Counterparty", "id_doc_file", "keeper"),
    ("registry.Specimen", "photo", "keeper"),
    ("registry.Marking", "photo", "specimen__keeper"),
    ("registry.CitesDocument", "file", "keeper"),
    ("declarations.Declaration", "pdf", "keeper"),
    ("declarations.Attachment", "file", "declaration__keeper"),
    ("declarations.Payment", "receipt", "keeper"),
    ("importer.ImportedFile", "file", "keeper"),
]


def _allowed(user, name: str) -> bool:
    from django.apps import apps

    keeper_ids = list(user.memberships.values_list("keeper_id", flat=True))
    for label, field, keeper_path in PROTECTED:
        model = apps.get_model(label)
        lookup = "pk__in" if not keeper_path else f"{keeper_path}__in"
        if model.objects.filter(**{field: name, lookup: keeper_ids}).exists():
            return True
    return False


@login_required
def protected_media(request, path):
    root = Path(settings.MEDIA_ROOT).resolve()
    full = (root / path).resolve()
    if root not in full.parents or not full.is_file() or not _allowed(request.user, path):
        raise Http404
    content_type, _ = mimetypes.guess_type(full.name)
    try:
        fh = default_storage.open(path)  # decrypts with the owner's (unlocked) key
    except VaultLocked:
        raise Http404 from None
    return FileResponse(fh, content_type=content_type or "application/octet-stream")
