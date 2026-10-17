import re

from django.core.exceptions import ValidationError

_CF_RE = re.compile(r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-EHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$")
_ODD = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17, 19, 21,
                 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]))


def codice_fiscale_is_valid(value: str) -> bool:
    cf = (value or "").upper().strip()
    if not _CF_RE.match(cf):
        return False
    total = 0
    for i, ch in enumerate(cf[:15]):
        if i % 2 == 0:  # odd positions (1-based)
            total += _ODD[ch]
        else:
            total += int(ch) if ch.isdigit() else ord(ch) - ord("A")
    return chr(ord("A") + total % 26) == cf[15]


def validate_codice_fiscale(value: str) -> None:
    if value and not codice_fiscale_is_valid(value):
        raise ValidationError("Codice fiscale non valido.")
