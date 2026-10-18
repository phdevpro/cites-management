"""Cryptographic primitives (no Django state).

Key hierarchy
-------------
* Every keeper (detentore) has a random 256-bit data key (DEK). It encrypts personal fields
  and files with AES-256-GCM.
* Every user has an X25519 key pair. The private key is stored encrypted twice:
  with a key derived from the user's passphrase (scrypt) and with a random recovery key
  that only the user holds.
* A keeper's DEK is sealed to the public key of each member (ephemeral X25519 + HKDF + AES-GCM),
  so an owner can share access without knowing the other member's secret.

The server stores only ciphertext, salts and public keys.
"""

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

NONCE = 12
KEY = 32


class DecryptionError(Exception):
    pass


def random_key() -> bytes:
    return os.urandom(KEY)


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --------------------------------------------------------------------------- AES-GCM

def seal(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(NONCE)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad or None)


def open_sealed(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    try:
        return AESGCM(key).decrypt(blob[:NONCE], blob[NONCE:], aad or None)
    except Exception as exc:  # InvalidTag, short input…
        raise DecryptionError("decryption failed") from exc


def hkdf(material: bytes, info: bytes, salt: bytes | None = None) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY, salt=salt, info=info).derive(material)


def keyed_hash(key: bytes, data: bytes) -> str:
    """Deterministic fingerprint (e.g. duplicate detection) that reveals nothing without the key."""
    return hmac.new(hkdf(key, b"cites-fingerprint"), data, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- passphrase / recovery

def derive_passphrase_key(passphrase: str, salt: bytes, n: int) -> bytes:
    return Scrypt(salt=salt, length=KEY, n=n, r=8, p=1).derive(passphrase.encode())


RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def new_recovery_code() -> str:
    """~160 bits, grouped for writing down: XXXX-XXXX-…"""
    raw = os.urandom(32)
    chars = [RECOVERY_ALPHABET[b % len(RECOVERY_ALPHABET)] for b in raw]
    return "-".join("".join(chars[i:i + 4]) for i in range(0, 32, 4))


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch in RECOVERY_ALPHABET)


def recovery_key(code: str) -> bytes:
    return hkdf(normalize_recovery_code(code).encode(), b"cites-recovery")


# --------------------------------------------------------------------------- key pairs

def new_keypair() -> tuple[bytes, bytes]:
    priv = X25519PrivateKey.generate()
    return (
        priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()),
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
    )


def public_from_private(private_raw: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(private_raw).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def wrap_for(public_raw: bytes, secret: bytes) -> bytes:
    """Seal `secret` so only the holder of the matching private key can open it."""
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    shared = eph.exchange(X25519PublicKey.from_public_bytes(public_raw))
    key = hkdf(shared, b"cites-dek-wrap", salt=eph_pub + public_raw)
    return eph_pub + seal(key, secret, b"cites-dek")


def unwrap(private_raw: bytes, blob: bytes) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(private_raw)
    eph_pub = blob[:32]
    shared = priv.exchange(X25519PublicKey.from_public_bytes(eph_pub))
    key = hkdf(shared, b"cites-dek-wrap", salt=eph_pub + public_from_private(private_raw))
    return open_sealed(key, blob[32:], b"cites-dek")
