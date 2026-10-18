"""Check the Regolo.ai configuration: key, model IDs and their capabilities."""

import httpx
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
        try:
            models = httpx.get(f"{base}/models", headers=headers, timeout=30).raise_for_status().json()
        except httpx.HTTPError as exc:
            raise CommandError(f"Chiamata a {base}/models fallita: {exc}") from None
        ids = sorted(m.get("id", "") for m in models.get("data", []))
        info = {}
        root = base.removesuffix("/v1")
        try:
            data = httpx.get(f"{root}/model_group/info", headers=headers, timeout=30).raise_for_status().json()
            info = {m.get("model_group"): m for m in data.get("data", [])}
        except httpx.HTTPError:
            pass
        self.stdout.write(f"{'modello':40} {'visione':8} {'input max':>10} {'modo':10}")
        for mid in ids:
            m = info.get(mid, {})
            self.stdout.write(f"{mid:40} {str(m.get('supports_vision', '?')):8} {str(m.get('max_input_tokens', '?')):>10} "
                              f"{str(m.get('mode', '')):10}")
        for label, wanted in (("OCR", settings.AI_OCR_MODEL), ("Estrazione", settings.AI_EXTRACT_MODEL)):
            ok = wanted in ids
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f"{label}: {wanted} {'OK' if ok else 'NON TROVATO: imposta il nome esatto nello stack'}"))
