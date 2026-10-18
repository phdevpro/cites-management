from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Azzera l'autenticazione a due fattori di un utente (telefono perso): al prossimo accesso la riconfigura."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, username, **opts):
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError("Utente inesistente.")
        n = TOTPDevice.objects.filter(user=user).delete()[0] + StaticDevice.objects.filter(user=user).delete()[0]
        self.stdout.write(self.style.SUCCESS(f"2FA azzerata per {username} ({n} dispositivi rimossi)."))
