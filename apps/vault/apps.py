from django.apps import AppConfig


class VaultConfig(AppConfig):
    name = "apps.vault"
    verbose_name = "Cifratura"

    def ready(self):
        from . import middleware  # noqa: F401  (registers the logout signal)
