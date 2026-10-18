from collections import Counter

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from apps.accounts.models import Keeper
from apps.dashboard.alerts import keeper_alerts


class Command(BaseCommand):
    help = ("Invia via email il numero di scadenze CITES imminenti/scadute ai membri di ogni detentore "
            "(da cron giornaliero). I dati personali sono cifrati: l'email non contiene dettagli.")

    def handle(self, *args, **opts):
        for keeper in Keeper.objects.all():
            alerts = [a for a in keeper_alerts(keeper) if a.level in ("danger", "warning")]
            if not alerts:
                continue
            emails = sorted({m.user.email for m in keeper.memberships.select_related("user") if m.user.email})
            if not emails:
                continue
            levels = Counter(a.level for a in alerts)
            body = (
                f"Hai {len(alerts)} scadenze CITES da gestire"
                f" ({levels['danger']} scadute, {levels['warning']} in scadenza).\n\n"
                "Accedi a CITES Manager per i dettagli."
            )
            send_mail(f"[CITES] {len(alerts)} scadenze", body, settings.DEFAULT_FROM_EMAIL, emails)
            self.stdout.write(f"profilo #{keeper.pk}: {len(alerts)} avvisi → {len(emails)} destinatari")
