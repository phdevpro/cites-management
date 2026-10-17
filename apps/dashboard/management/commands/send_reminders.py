from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from apps.accounts.models import Keeper
from apps.dashboard.alerts import keeper_alerts


class Command(BaseCommand):
    help = "Invia via email le scadenze CITES imminenti/scadute ai membri di ogni detentore (da cron giornaliero)."

    def handle(self, *args, **opts):
        for keeper in Keeper.objects.all():
            alerts = [a for a in keeper_alerts(keeper) if a.level in ("danger", "warning")]
            if not alerts:
                continue
            emails = {m.user.email for m in keeper.memberships.select_related("user") if m.user.email}
            if keeper.email:
                emails.add(keeper.email)
            if not emails:
                continue
            body = "\n".join(
                f"- {a.title}: {a.detail}" + (f" (scadenza {a.due:%d/%m/%Y})" if a.due else "") for a in alerts
            )
            send_mail(f"[CITES] {len(alerts)} scadenze per {keeper}", body, settings.DEFAULT_FROM_EMAIL, sorted(emails))
            self.stdout.write(f"{keeper}: {len(alerts)} avvisi → {', '.join(sorted(emails))}")
