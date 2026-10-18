"""Create a demo user + keeper with synthetic data (development only)."""

import os
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import CitesOffice, DetentionSite, Keeper, Membership
from apps.declarations import services
from apps.registry.models import CitesDocument, Counterparty
from apps.species.models import Species
from apps.vault import services as vault
from apps.vault.context import using


class Command(BaseCommand):
    help = "Crea utente 'demo' (password da DEMO_PASSWORD, default 'demo-cites-2026') con dati di esempio."

    def handle(self, *args, **opts):
        call_command("load_initial_data")
        password = os.environ.get("DEMO_PASSWORD", "demo-cites-2026")
        user, _ = User.objects.get_or_create(username="demo", defaults={"email": "demo@example.com",
                                                                        "is_staff": True, "is_superuser": True})
        user.set_password(password)
        user.save()
        if Membership.objects.filter(user=user).exists():
            self.stdout.write("Demo già presente.")
            return
        # demo passphrase = DEMO_PASSWORD; recovery code printed once
        private, code = vault.create_user_key(user, password)
        vault.confirm_recovery(user, code)
        ring = vault.keyring_for(user, private)
        with using(ring):
            self._seed(user)
        self.stdout.write(self.style.SUCCESS(
            f"Utente demo creato. Passphrase di cifratura = password demo. Chiave di recupero: {code}"))

    def _seed(self, user):
        keeper = Keeper(
            first_name="Mario", last_name="Rossi", birth_place="Udine", birth_province="UD",
            birth_date=date(1980, 1, 1), address="Via Roma 1", postal_code="33100", city="Udine", province="UD",
            phone="+39 333 0000000", email="demo@example.com", id_doc_number="AA0000000",
            cites_office=CitesOffice.objects.first(), sells_specimens=True,
        )
        dek = vault.new_keeper_key(keeper)
        keeper.save()
        DetentionSite.objects.create(keeper=keeper, address="Via Roma 1", postal_code="33100", city="Udine",
                                     province="UD", phone="+39 333 0000000")
        vault.share_with(Membership.objects.create(user=user, keeper=keeper, role="owner"), dek)
        th = Species.objects.get(scientific_name="Testudo hermanni")
        old = CitesDocument.objects.create(keeper=keeper, doc_type="old", number="PROT 123 DEL 1999",
                                           issued_on=date(1995, 5, 1))
        male = services.register_acquisition(keeper=keeper, user=user, species=th, quantity=1, sex="M",
                                             acquired_on=date(1995, 5, 1), counterparty=None, name="Ercole",
                                             origin="pre", document=old)
        female = services.register_acquisition(keeper=keeper, user=user, species=th, quantity=1, sex="F",
                                               acquired_on=date(1995, 5, 1), counterparty=None, name="Giunone",
                                               origin="pre", document=old)
        last_year = services.register_birth(keeper=keeper, user=user, species=th, birth_date=date(2024, 10, 18),
                                            rows=[services.NewbornSpec(quantity=9)], father=male, mother=female,
                                            breeding_group="PROT 123 DEL 1999")
        services.mark_sent(last_year.declaration, date(2024, 10, 26), "pec")
        services.mark_protocolled(last_year.declaration, "1234 (10.100-1)", date(2024, 10, 31))
        services.register_death(keeper=keeper, user=user, specimen=last_year.specimens[0], quantity=1,
                                death_date=date(2025, 7, 15))
        services.register_birth(keeper=keeper, user=user, species=th,
                                birth_date=timezone.localdate() - timedelta(days=4),
                                rows=[services.NewbornSpec(quantity=7)], father=male, mother=female,
                                breeding_group="PROT 123 DEL 1999")
        Counterparty.objects.create(keeper=keeper, first_name="Luigi", last_name="Verdi", address="Via Garibaldi 5",
                                    postal_code="34100", city="Trieste", province="TS", phone="+39 333 1111111")
