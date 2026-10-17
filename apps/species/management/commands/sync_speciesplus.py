"""Sync EU annex / CITES appendix from Species+ (https://api.speciesplus.net)."""

import json
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.species.models import Species

API = "https://api.speciesplus.net/api/v1/"


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(API + path, headers={"X-Authentication-Token": token})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


class Command(BaseCommand):
    help = "Aggiorna allegato UE e appendice CITES delle specie da Species+ (richiede SPECIESPLUS_TOKEN)."

    def add_arguments(self, parser):
        parser.add_argument("--species", help="Solo questa specie (nome scientifico)")

    def handle(self, *args, **opts):
        token = settings.SPECIESPLUS_TOKEN
        if not token:
            raise CommandError("SPECIESPLUS_TOKEN non impostato.")
        qs = Species.objects.all()
        if opts["species"]:
            qs = qs.filter(scientific_name__iexact=opts["species"])
        for sp in qs:
            try:
                if not sp.speciesplus_id:
                    data = _get("taxon_concepts?" + urllib.parse.urlencode({"name": sp.scientific_name}), token)
                    concepts = data.get("taxon_concepts") or []
                    if not concepts:
                        self.stdout.write(self.style.WARNING(f"{sp}: non trovata"))
                        continue
                    sp.speciesplus_id = concepts[0]["id"]
                    listings = concepts[0].get("cites_listings") or []
                    current = [l["appendix"] for l in listings if l.get("appendix")]
                    if current:
                        sp.cites_appendix = "/".join(sorted(set(current)))
                eu = _get(f"taxon_concepts/{sp.speciesplus_id}/eu_legislation", token)
                annexes = [l["annex"] for l in eu.get("eu_listings", []) if l.get("is_current") and l.get("annex")]
                new_annex = sorted(annexes)[0] if annexes else ""
                if new_annex != sp.eu_annex:
                    self.stdout.write(self.style.WARNING(f"{sp}: allegato {sp.eu_annex or '-'} → {new_annex or '-'}"))
                    if new_annex == "A":
                        sp.annex_changed_on = timezone.localdate()
                    sp.eu_annex = new_annex
                sp.annex_checked_at = timezone.now()
                sp.save()
                self.stdout.write(f"{sp}: OK ({sp.eu_annex}, App. {sp.cites_appendix})")
            except Exception as exc:  # network / API errors per species
                self.stdout.write(self.style.ERROR(f"{sp}: {exc}"))
