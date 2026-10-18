"""Unlocked keys for the current request / command (never persisted server-side)."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


class VaultLocked(Exception):
    """Encrypted data needed but the keeper's key is not unlocked."""


@dataclass
class KeyRing:
    private_key: bytes | None = None
    keys: dict = field(default_factory=dict)  # key_id -> DEK
    keeper_keys: dict = field(default_factory=dict)  # keeper pk -> key_id
    write_key_id: str | None = None  # key used by file storage when no instance is known
    dirty: bool = False  # keys added during the request: cookie must be rewritten

    def add(self, keeper_id, key_id: str, dek: bytes):
        self.keys[key_id] = dek
        if keeper_id is not None:
            self.keeper_keys[keeper_id] = key_id
        self.dirty = True

    def dek(self, key_id: str) -> bytes:
        try:
            return self.keys[key_id]
        except KeyError:
            raise VaultLocked(key_id) from None


_ring: ContextVar[KeyRing] = ContextVar("cites_keyring")


def ring() -> KeyRing:
    try:
        return _ring.get()
    except LookupError:
        r = KeyRing()
        _ring.set(r)
        return r


def activate(r: KeyRing):
    return _ring.set(r)


def deactivate(token):
    _ring.reset(token)


@contextmanager
def using(r: KeyRing):
    token = _ring.set(r)
    try:
        yield r
    finally:
        _ring.reset(token)


@contextmanager
def writing_with(key_id: str | None):
    r = ring()
    previous = r.write_key_id
    r.write_key_id = key_id
    try:
        yield
    finally:
        r.write_key_id = previous
