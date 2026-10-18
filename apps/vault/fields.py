"""Model fields stored encrypted with the owning keeper's data key.

Stored format: ``enc1:<key_id>:<base64(nonce|ciphertext)>`` with AAD = key_id + column name.
Empty values are stored as-is. Rows of keepers that are not yet encrypted (no key_id) are
stored in clear until the owner enables encryption (see services.encrypt_keeper).
"""

import datetime
import json

from django.db import models

from . import crypto
from .context import VaultLocked, ring

PREFIX = "enc1:"


class Locked(str):
    """Placeholder returned when the key is not unlocked; saving it keeps the original ciphertext."""

    def __new__(cls, raw):
        obj = super().__new__(cls, "🔒")
        obj.raw = raw
        return obj


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt_str(key_id: str, plaintext: str, column: str) -> str:
    dek = ring().dek(key_id)
    blob = crypto.seal(dek, plaintext.encode(), f"{key_id}:{column}".encode())
    return f"{PREFIX}{key_id}:{crypto.b64e(blob)}"


def decrypt_str(value: str, column: str):
    _, key_id, payload = value.split(":", 2)
    try:
        dek = ring().dek(key_id)
    except VaultLocked:
        return Locked(value)
    return crypto.open_sealed(dek, crypto.b64d(payload), f"{key_id}:{column}".encode()).decode()


def _keeper_key_id(keeper_id):
    if keeper_id is None:
        return None
    r = ring()
    if keeper_id in r.keeper_keys:
        return r.keeper_keys[keeper_id]
    from apps.accounts.models import Keeper

    key_id = Keeper.objects.filter(pk=keeper_id).values_list("key_id", flat=True).first()
    if key_id:
        r.keeper_keys[keeper_id] = key_id
    return key_id


def key_id_for(instance):
    """Key of the keeper owning `instance` (also works for simple_history rows)."""
    if instance._meta.model_name in ("keeper", "historicalkeeper"):
        return instance.key_id
    keeper_id = getattr(instance, "keeper_id", None)
    if keeper_id is None and getattr(instance, "specimen_id", None):
        from apps.registry.models import Specimen

        keeper_id = Specimen.objects.filter(pk=instance.specimen_id).values_list("keeper_id", flat=True).first()
    if keeper_id is None and getattr(instance, "declaration_id", None):
        from apps.declarations.models import Declaration

        keeper_id = Declaration.objects.filter(pk=instance.declaration_id).values_list("keeper_id", flat=True).first()
    return _keeper_key_id(keeper_id)


class EncryptedMixin:
    """Mixin for scalar fields: python value <-> text, encrypted in pre_save, decrypted in from_db_value."""

    def get_internal_type(self):
        return "TextField"

    def db_type(self, connection):
        return connection.data_types["TextField"]

    def encode(self, value) -> str:
        return str(value)

    def decode(self, text: str):
        return text

    def from_db_value(self, value, expression, connection):
        if value is None or value == "" or not is_encrypted(value):
            return self.decode(value) if value else value
        plain = decrypt_str(value, self.column)
        return plain if isinstance(plain, Locked) else self.decode(plain)

    def pre_save(self, model_instance, add):
        value = super().pre_save(model_instance, add)
        if isinstance(value, Locked):
            return value.raw
        if value is None or value == "":
            return value
        key_id = key_id_for(model_instance)
        if not key_id:
            return value  # keeper not encrypted (yet)
        return encrypt_str(key_id, self.encode(value), self.column)

    def get_db_prep_value(self, value, connection, prepared=False):
        if is_encrypted(value):
            return value
        if not prepared and value not in (None, ""):
            value = self.get_prep_value(value)
        return self.encode(value) if value not in (None, "") else value

    def to_python(self, value):
        if isinstance(value, Locked):
            return value
        return super().to_python(value)


class EncryptedCharField(EncryptedMixin, models.CharField):
    pass


class EncryptedTextField(EncryptedMixin, models.TextField):
    pass


class EncryptedEmailField(EncryptedMixin, models.EmailField):
    pass


class EncryptedDateField(EncryptedMixin, models.DateField):
    def encode(self, value):
        return value.isoformat() if isinstance(value, datetime.date) else str(value)

    def decode(self, text):
        return datetime.date.fromisoformat(text) if text else None

    def get_db_prep_value(self, value, connection, prepared=False):
        if is_encrypted(value) or value in (None, ""):
            return value or None
        return self.encode(self.to_python(value))


class EncryptedJSONField(EncryptedMixin, models.TextField):
    """JSON document stored as encrypted text (python value: dict/list)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("default", dict)
        super().__init__(*args, **kwargs)

    def encode(self, value):
        return json.dumps(value, ensure_ascii=False, default=str)

    def decode(self, text):
        return json.loads(text) if text else {}

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return {}
        return super().from_db_value(value, expression, connection)

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if isinstance(value, Locked):
            return value.raw
        key_id = key_id_for(model_instance)
        if not key_id:
            return self.encode(value if value is not None else {})
        return encrypt_str(key_id, self.encode(value if value is not None else {}), self.column)

    def get_db_prep_value(self, value, connection, prepared=False):
        if isinstance(value, str):
            return value
        return self.encode(value if value is not None else {})

    def to_python(self, value):
        if isinstance(value, (dict, list)) or value is None:
            return value
        return self.decode(value)

    def value_to_string(self, obj):
        return self.encode(self.value_from_object(obj))
