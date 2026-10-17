from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Keeper
from apps.importer import services
from apps.importer.models import ImportBatch


class Command(BaseCommand):
    help = "Importa una cartella di archivio (es. 'CITES Denuncia Tartarughe') per un detentore; poi verifica dal web."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--keeper", type=int, required=True, help="ID del detentore")

    def handle(self, *args, path, keeper, **opts):
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
            self.stdout.write(f"{f.original_path:70.70} {f.method:8} {f.detected_kind:6} {f.confidence:.2f}")
        self.stdout.write(self.style.SUCCESS(f"{batch.files.count()} file → /importa/lotto/{batch.pk}/"))
