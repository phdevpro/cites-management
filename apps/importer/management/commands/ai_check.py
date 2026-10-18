"""Check the Regolo.ai configuration: key, model IDs and their capabilities."""

import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.importer import ai


class Command(BaseCommand):
    help = "Verifica la chiave Regolo.ai ed elenca i modelli disponibili (visione, contesto, prezzi)."

    def handle(self, *args, **opts):
        if not ai.enabled():
            raise CommandError("REGOLO_API_KEY non impostata: l'import usa solo la lettura locale.")
        headers = {"Authorization": f"Bearer {settings.REGOLO_API_KEY}"}
        base = settings.REGOLO_BASE_URL.rstrip("/")

        def get(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                return json.loads(resp.read())

        try:
            models = get(f"{base}/models")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise CommandError("Chiave Regolo non valida o revocata (HTTP %s)." % exc.code) from None
            raise CommandError(f"Chiamata a {base}/models fallita: {exc}") from None
        except (OSError, ValueError) as exc:
            raise CommandError(f"Chiamata a {base}/models fallita: {exc}") from None
        ids = sorted(m.get("id", "") for m in models.get("data", []))
        info = {}
        root = base.removesuffix("/v1")
        try:
            info = {m.get("model_group"): m for m in get(f"{root}/model_group/info").get("data", [])}
        except (OSError, ValueError):
            pass
        self.stdout.write(f"{'modello':40} {'visione':8} {'input max':>10} {'modo':10}")
        for mid in ids:
            m = info.get(mid, {})
            self.stdout.write(f"{mid:40} {str(m.get('supports_vision', '?')):8} {str(m.get('max_input_tokens', '?')):>10} "
                              f"{str(m.get('mode', '')):10}")
        problems = ai.check_key(settings.REGOLO_API_KEY)
        for p in problems:
            self.stdout.write(self.style.ERROR(p))
        if not problems:
            self.stdout.write(self.style.SUCCESS(f"OCR: {settings.AI_OCR_MODEL} OK"))
            self.stdout.write(self.style.SUCCESS(f"Estrazione: {settings.AI_EXTRACT_MODEL} OK"))
