from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Carica dati iniziali: specie, diritti di prelievo (avviso MASE 10/10/2024), uffici CITES."

    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="Carica solo se il database non ha specie.")

    def handle(self, *args, **options):
        from apps.species.models import Species

        if options["if_empty"] and Species.objects.exists():
            self.stdout.write("Dati iniziali già presenti.")
            return
        for fixture in ("species", "fees", "offices"):
            call_command("loaddata", fixture, verbosity=1)
