import getpass
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Keeper, Membership
from apps.importer import services
from apps.importer.models import ImportBatch
from apps.vault import services as vault
from apps.vault.context import using


class Command(BaseCommand):
    help = "Importa una cartella di archivio (es. 'CITES Denuncia Tartarughe') per un detentore; poi verifica dal web."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--keeper", type=int, required=True, help="ID del detentore")
        parser.add_argument("--user", required=True, help="Username di un membro del detentore (per sbloccare i dati)")

    def handle(self, *args, path, keeper, user, **opts):
        u = User.objects.filter(username=user).first()
        if not u or not Membership.objects.filter(user=u, keeper_id=keeper).exists():
            raise CommandError("Utente non membro del detentore.")
        try:
            private = vault.unlock_private_key(u, getpass.getpass("Passphrase di cifratura: "))
        except vault.VaultError as exc:
            raise CommandError(str(exc)) from None
        with using(vault.keyring_for(u, private)):
            self._import(path, keeper)

    def _import(self, path, keeper):
        root = Path(path)
        if not root.is_dir():
            raise CommandError(f"{root} non è una cartella")
        k = Keeper.objects.filter(pk=keeper).first()
        if not k:
            raise CommandError("Detentore inesistente")
        batch = ImportBatch.objects.create(keeper=k, label=f"Archivio {root.name}")
        for msg in services.add_path(batch, root):
            self.stdout.write(self.style.WARNING(msg))
        for f in batch.files.all():
            self.stdout.write(f"{f.method:8} {f.detected_kind:6} {f.confidence:.2f}")
        self.stdout.write(self.style.SUCCESS(f"{batch.files.count()} file → /importa/lotto/{batch.pk}/"))
