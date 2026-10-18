"""Encrypted uploads.

* File names are replaced by random ids (names like "Rossi Mario CI.pdf" reveal personal data);
  the original name lives in encrypted model fields where needed.
* Contents are AES-GCM encrypted with the owning keeper's key: MAGIC | key_id (32 hex) | nonce | ct.
* Files of keepers that are not yet encrypted are stored in clear (migrated by encrypt_keeper).
"""

import uuid
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db.models.fields.files import FieldFile, FileField, ImageField, ImageFieldFile

from . import crypto
from .context import ring, writing_with
from .fields import key_id_for

MAGIC = b"CITESENC1"


def encrypt_bytes(key_id: str, data: bytes) -> bytes:
    return MAGIC + key_id.encode() + crypto.seal(ring().dek(key_id), data, MAGIC + key_id.encode())


def decrypt_bytes(data: bytes) -> bytes:
    if not data.startswith(MAGIC):
        return data  # legacy clear file
    key_id = data[len(MAGIC):len(MAGIC) + 32].decode()
    return crypto.open_sealed(ring().dek(key_id), data[len(MAGIC) + 32:], MAGIC + key_id.encode())


def is_encrypted_file(data: bytes) -> bool:
    return data.startswith(MAGIC)


class EncryptedFileSystemStorage(FileSystemStorage):
    def generate_filename(self, filename):
        path = PurePosixPath(filename)
        suffix = "".join(path.suffixes[-1:]).lower()[:10]
        return str(path.parent / f"{uuid.uuid4().hex}{suffix}")

    def _save(self, name, content):
        key_id = ring().write_key_id
        if key_id:
            if hasattr(content, "seek"):
                content.seek(0)
            data = content.read()
            content = ContentFile(encrypt_bytes(key_id, data))
        return super()._save(name, content)

    def _open(self, name, mode="rb"):
        with super()._open(name, "rb") as fh:
            raw = fh.read()
        f = ContentFile(decrypt_bytes(raw), name=name)
        f.mode = mode
        return f

    def size(self, name):
        with super()._open(name, "rb") as fh:
            head = fh.read(len(MAGIC))
        size = super().size(name)
        return size - len(MAGIC) - 32 - 12 - 16 if head == MAGIC else size


class _KeyedSaveMixin:
    def save(self, name, content, save=True):
        with writing_with(key_id_for(self.instance)):
            super().save(name, content, save)


class EncryptedFieldFile(_KeyedSaveMixin, FieldFile):
    pass


class EncryptedImageFieldFile(_KeyedSaveMixin, ImageFieldFile):
    pass


class EncryptedFileField(FileField):
    attr_class = EncryptedFieldFile


class EncryptedImageField(ImageField):
    attr_class = EncryptedImageFieldFile


def read_plain(field_file) -> bytes:
    """Decrypted content of a stored file."""
    field_file.open("rb")
    try:
        return field_file.read()
    finally:
        field_file.close()

