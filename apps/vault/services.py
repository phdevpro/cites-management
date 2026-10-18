import json
import time
import uuid

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from . import crypto
from .context import KeyRing, ring, writing_with
from .fields import EncryptedMixin, Locked
from .models import UserKey
from .storage import EncryptedFileField, EncryptedImageField, encrypt_bytes, is_encrypted_file

MIN_PASSPHRASE = 12
COOKIE_NAME = "cites_vault"


class VaultError(Exception):
    pass


def _scrypt_n():
    return getattr(settings, "VAULT_SCRYPT_N", 2 ** 15)


# --------------------------------------------------------------------------- user keys

@transaction.atomic
def create_user_key(user, passphrase: str) -> tuple[bytes, str]:
    """Generate the user's key pair. Returns (private key, recovery code shown once)."""
    if len(passphrase) < MIN_PASSPHRASE:
        raise VaultError(f"La passphrase deve avere almeno {MIN_PASSPHRASE} caratteri.")
    private, public = crypto.new_keypair()
    salt = crypto.random_key()[:16]
    n = _scrypt_n()
    code = crypto.new_recovery_code()
    UserKey.objects.update_or_create(user=user, defaults={
        "public_key": public,
        "salt": salt,
        "scrypt_n": n,
        "private_by_passphrase": crypto.seal(crypto.derive_passphrase_key(passphrase, salt, n), private, b"user-key"),
        "private_by_recovery": crypto.seal(crypto.recovery_key(code), private, b"user-key"),
        "recovery_confirmed": False,
    })
    return private, code


def unlock_private_key(user, passphrase: str) -> bytes:
    uk = UserKey.objects.filter(user=user).first()
    if uk is None:
        raise VaultError("Cifratura non configurata.")
    try:
        key = crypto.derive_passphrase_key(passphrase, bytes(uk.salt), uk.scrypt_n)
        return crypto.open_sealed(key, bytes(uk.private_by_passphrase), b"user-key")
    except crypto.DecryptionError:
        raise VaultError("Passphrase errata.") from None


def private_key_from_recovery(user, code: str) -> bytes:
    uk = UserKey.objects.filter(user=user).first()
    if uk is None:
        raise VaultError("Cifratura non configurata.")
    try:
        return crypto.open_sealed(crypto.recovery_key(code), bytes(uk.private_by_recovery), b"user-key")
    except crypto.DecryptionError:
        raise VaultError("Chiave di recupero errata.") from None


def confirm_recovery(user, code: str) -> None:
    private_key_from_recovery(user, code)
    UserKey.objects.filter(user=user).update(recovery_confirmed=True)


def set_passphrase(user, private: bytes, new_passphrase: str) -> None:
    if len(new_passphrase) < MIN_PASSPHRASE:
        raise VaultError(f"La passphrase deve avere almeno {MIN_PASSPHRASE} caratteri.")
    uk = UserKey.objects.get(user=user)
    salt = crypto.random_key()[:16]
    n = _scrypt_n()
    uk.salt = salt
    uk.scrypt_n = n
    uk.private_by_passphrase = crypto.seal(crypto.derive_passphrase_key(new_passphrase, salt, n), private, b"user-key")
    uk.save()


def new_recovery_code(user, private: bytes) -> str:
    code = crypto.new_recovery_code()
    UserKey.objects.filter(user=user).update(
        private_by_recovery=crypto.seal(crypto.recovery_key(code), private, b"user-key"), recovery_confirmed=False
    )
    return code


# --------------------------------------------------------------------------- keeper keys

def keyring_for(user, private: bytes) -> KeyRing:
    """Unwrap the data keys of every keeper the user is a member of."""
    from apps.accounts.models import Membership

    r = KeyRing(private_key=private)
    for m in Membership.objects.filter(user=user).select_related("keeper"):
        if m.keeper.key_id and m.wrapped_dek:
            try:
                r.add(m.keeper_id, m.keeper.key_id, crypto.unwrap(private, bytes(m.wrapped_dek)))
            except crypto.DecryptionError:
                continue
    r.dirty = False
    return r


def new_keeper_key(keeper) -> bytes:
    """Assign a fresh data key to a (new) keeper before it is saved; registers it in the active ring."""
    dek = crypto.random_key()
    keeper.key_id = uuid.uuid4().hex
    ring().add(keeper.pk, keeper.key_id, dek)
    return dek


def share_with(membership, dek: bytes) -> bool:
    """Seal the keeper's data key for this member. False if the member has no key pair yet."""
    uk = UserKey.objects.filter(user=membership.user).first()
    if uk is None:
        return False
    membership.wrapped_dek = crypto.wrap_for(bytes(uk.public_key), dek)
    membership.save(update_fields=["wrapped_dek"])
    return True


def keeper_dek(keeper) -> bytes:
    return ring().dek(keeper.key_id)


# --------------------------------------------------------------------------- encrypting existing data

def _keeper_lookup(model):
    """Filter kwargs to select a model's rows for a keeper (None = model not keeper-owned)."""
    names = {f.name for f in model._meta.get_fields()}
    if model._meta.model_name in ("keeper", "historicalkeeper"):
        return "pk" if model._meta.model_name == "keeper" else "id"
    if "keeper" in names:
        return "keeper"
    if "specimen" in names:
        return "specimen__keeper"
    if "declaration" in names:
        return "declaration__keeper"
    return None


def _encrypted_columns(model):
    return [f for f in model._meta.concrete_fields if isinstance(f, EncryptedMixin)]


def _file_columns(model):
    return [f for f in model._meta.concrete_fields if isinstance(f, (EncryptedFileField, EncryptedImageField))]


@transaction.atomic
def encrypt_keeper(keeper, owner) -> bytes:
    """Give a clear-text (pre-encryption) keeper a data key, then rewrite all its rows,
    history rows and files encrypted. Members other than `owner` are shared if they have a key pair."""
    from apps.accounts.models import Keeper, Membership

    if keeper.key_id:
        raise VaultError("Profilo già cifrato.")
    dek = new_keeper_key(keeper)
    Keeper.objects.filter(pk=keeper.pk).update(key_id=keeper.key_id)
    for m in Membership.objects.filter(keeper=keeper).select_related("user"):
        share_with(m, dek)

    for model in apps.get_models():
        cols, files = _encrypted_columns(model), _file_columns(model)
        if not (cols or files):
            continue
        lookup = _keeper_lookup(model)
        if lookup is None:
            continue
        for obj in model._default_manager.filter(**{lookup: keeper.pk}).iterator():
            updates = {}
            for f in cols:
                value = getattr(obj, f.attname)
                if isinstance(value, Locked):
                    continue
                updates[f.attname] = f.pre_save(obj, False)
            for f in files:
                ff = getattr(obj, f.attname)
                if not ff or not ff.name:
                    continue
                storage = ff.storage
                if not storage.exists(ff.name):
                    continue
                with storage.open(ff.name) as fh:
                    data = fh.read()
                if is_encrypted_file(data):
                    continue
                with writing_with(keeper.key_id):
                    new_name = storage.save(f.generate_filename(obj, "x" + _suffix(ff.name)), ContentFile(data))
                # remove the clear original only once the whole conversion is committed
                transaction.on_commit(lambda s=storage, n=ff.name: s.delete(n))
                updates[f.attname] = new_name
            if updates:
                model._default_manager.filter(pk=obj.pk).update(**updates)
    return dek


def _suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > name.rfind("/") else ""


# --------------------------------------------------------------------------- browser cookie

def _cookie_key() -> bytes:
    return crypto.hkdf(settings.SECRET_KEY.encode(), b"cites-vault-cookie")


def dump_cookie(r: KeyRing, session_key: str) -> str:
    payload = {
        "p": crypto.b64e(r.private_key),
        "k": {kid: crypto.b64e(dek) for kid, dek in r.keys.items()},
        "m": {str(k): v for k, v in r.keeper_keys.items()},
        "t": int(time.time()),
    }
    return crypto.b64e(crypto.seal(_cookie_key(), json.dumps(payload).encode(), session_key.encode()))


def load_cookie(value: str, session_key: str, max_age: int) -> KeyRing | None:
    try:
        payload = json.loads(crypto.open_sealed(_cookie_key(), crypto.b64d(value), session_key.encode()))
    except (crypto.DecryptionError, ValueError):
        return None
    if time.time() - payload.get("t", 0) > max_age:
        return None
    r = KeyRing(private_key=crypto.b64d(payload["p"]))
    r.keys = {kid: crypto.b64d(v) for kid, v in payload["k"].items()}
    r.keeper_keys = {int(k): v for k, v in payload["m"].items()}
    return r

