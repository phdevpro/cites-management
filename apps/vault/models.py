from django.conf import settings
from django.db import models


class UserKey(models.Model):
    """A user's X25519 key pair; the private key is only stored encrypted."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vault_key")
    public_key = models.BinaryField()
    salt = models.BinaryField()
    scrypt_n = models.PositiveIntegerField()
    private_by_passphrase = models.BinaryField()
    private_by_recovery = models.BinaryField()
    recovery_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Chiave di {self.user}"
