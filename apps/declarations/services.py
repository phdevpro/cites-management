"""Domain services. All registry state changes tied to CITES events go through here,
so specimens, declarations and the carico/scarico register stay consistent."""

from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.registry.models import CitesDocument, Counterparty, Marking, RegisterEntry, Specimen

from .models import Declaration, DeclarationItem


class ServiceError(Exception):
    pass


@dataclass
class NewbornSpec:
    """One row of a birth declaration: either one marked animal or an unmarked lot."""

    quantity: int = 1
    sex: str = Specimen.Sex.UNKNOWN
    name: str = ""
    marking_kind: str = ""
    marking_code: str = ""
    marking_manufacturer: str = ""


@dataclass
class TransferLine:
    specimen: Specimen
    quantity: int = 1
    document: CitesDocument | None = None


@dataclass
class BirthResult:
    declaration: Declaration | None
    specimens: list = field(default_factory=list)


# --------------------------------------------------------------------------- helpers

def check_microchip_free(keeper, kind: str, code: str) -> None:
    """Microchip codes are encrypted in the DB, so uniqueness is checked here (per keeper)."""
    if kind != Marking.Kind.MICROCHIP or not code:
        return
    wanted = code.replace(" ", "")
    for m in Marking.objects.filter(specimen__keeper=keeper, kind=Marking.Kind.MICROCHIP):
        if m.code.replace(" ", "") == wanted:
            raise ServiceError(f"Microchip {code} già assegnato a {m.specimen}.")


def split_lot(specimen: Specimen, quantity: int) -> Specimen:
    """Detach `quantity` animals from a lot into a new Specimen record. Returns the part to act on."""
    if quantity < 1 or quantity > specimen.quantity:
        raise ServiceError(f"Quantità {quantity} non valida per {specimen} (disponibili {specimen.quantity}).")
    if quantity == specimen.quantity:
        return specimen
    with transaction.atomic():
        specimen.quantity -= quantity
        specimen.save(update_fields=["quantity"])
        part = Specimen.objects.get(pk=specimen.pk)
        part.pk = None
        part.id = None
        part.quantity = quantity
        part.split_from = specimen
        part.save()
        part.cites_documents.set(specimen.cites_documents.all())
        return part


def _root_lot(specimen: Specimen) -> Specimen:
    seen = set()
    while specimen.split_from_id and specimen.pk not in seen:
        seen.add(specimen.pk)
        specimen = specimen.split_from
    return specimen


def _last_carico(specimen: Specimen):
    node, seen = specimen, set()
    while node and node.pk not in seen:
        seen.add(node.pk)
        entry = node.register_entries.filter(direction=RegisterEntry.Direction.IN).order_by("-number").first()
        if entry:
            return entry
        node = node.split_from
    return None


def _register(keeper, user, specimen, direction, cause, event_date, quantity, counterparty="", document="", notes=""):
    return RegisterEntry.objects.create(
        keeper=keeper,
        register_type=RegisterEntry.register_type_for(specimen.species),
        direction=direction,
        cause=cause,
        event_date=event_date,
        species=specimen.species,
        specimen=specimen,
        quantity=quantity,
        marking=specimen.markings_label,
        document=document,
        counterparty=counterparty,
        carico_ref=_last_carico(specimen) if direction == RegisterEntry.Direction.OUT else None,
        notes=notes,
        created_by=user,
    )


def _office(keeper):
    return keeper.cites_office


def _place(keeper):
    site = keeper.default_site
    return (site.city if site else "") or keeper.city


def _close_status(specimen: Specimen, status: str, when: date):
    specimen.status = status
    specimen.status_date = when
    specimen.save(update_fields=["status", "status_date"])


# --------------------------------------------------------------------------- births

@transaction.atomic
def register_birth(*, keeper, user, species, birth_date, rows: list[NewbornSpec], father=None, mother=None,
                   breeding_group="", site=None) -> BirthResult:
    if not rows:
        raise ServiceError("Indicare almeno un esemplare nato.")
    site = site or keeper.default_site
    specimens = []
    for row in rows:
        sp = Specimen.objects.create(
            keeper=keeper, species=species, site=site, name=row.name, quantity=row.quantity, sex=row.sex,
            birth_date=birth_date, origin=Specimen.Origin.BORN_HERE, source_code=Specimen.SourceCode.C,
            father=father, mother=mother, breeding_group=breeding_group,
        )
        if row.marking_kind:
            check_microchip_free(keeper, row.marking_kind, row.marking_code)
            Marking.objects.create(
                specimen=sp, kind=row.marking_kind, code=row.marking_code,
                manufacturer=row.marking_manufacturer, applied_on=birth_date,
            )
        _register(keeper, user, sp, RegisterEntry.Direction.IN, RegisterEntry.Cause.BIRTH, birth_date, sp.quantity,
                  counterparty="nato in allevamento")
        specimens.append(sp)

    kind = {"A": Declaration.Kind.BIRTH_A, "B": Declaration.Kind.BIRTH_B}.get(species.eu_annex)
    declaration = None
    if kind:
        declaration = Declaration.objects.create(
            keeper=keeper, kind=kind, office=_office(keeper), event_date=birth_date, place=_place(keeper),
            created_by=user,
        )
        for sp in specimens:
            DeclarationItem.objects.create(declaration=declaration, specimen=sp, quantity=sp.quantity)
    return BirthResult(declaration=declaration, specimens=specimens)


# --------------------------------------------------------------------------- deaths / losses

@transaction.atomic
def register_death(*, keeper, user, specimen: Specimen, quantity: int, death_date: date, cause: str = "",
                   document: CitesDocument | None = None) -> Declaration | None:
    if specimen.keeper_id != keeper.pk:
        raise ServiceError("Esemplare di un altro detentore.")
    if not specimen.is_alive:
        raise ServiceError(f"{specimen} non è vivo/detenuto.")
    part = split_lot(specimen, quantity)
    part.cause_of_death = cause
    _close_status(part, Specimen.Status.DEAD, death_date)
    part.save(update_fields=["cause_of_death"])
    document = document or part.current_document
    _register(keeper, user, part, RegisterEntry.Direction.OUT, RegisterEntry.Cause.DEATH, death_date, quantity,
              document=document.form_label if document else "", notes=cause)
    if part.species.eu_annex != "A":
        return None
    declaration = Declaration.objects.create(
        keeper=keeper, kind=Declaration.Kind.DEATH, office=_office(keeper), event_date=death_date,
        place=_place(keeper), created_by=user, notes=cause,
    )
    DeclarationItem.objects.create(declaration=declaration, specimen=part, quantity=quantity, document=document)
    return declaration


@transaction.atomic
def register_loss(*, keeper, user, specimen: Specimen, quantity: int, event_date: date, status: str,
                  circumstances: str = "") -> Declaration:
    if status not in (Specimen.Status.LOST, Specimen.Status.ESCAPED, Specimen.Status.STOLEN):
        raise ServiceError("Stato non valido per smarrimento.")
    part = split_lot(specimen, quantity)
    _close_status(part, status, event_date)
    document = part.current_document
    _register(keeper, user, part, RegisterEntry.Direction.OUT, RegisterEntry.Cause.LOSS, event_date, quantity,
              document=document.form_label if document else "", notes=circumstances)
    declaration = Declaration.objects.create(
        keeper=keeper, kind=Declaration.Kind.LOSS, office=_office(keeper), event_date=event_date,
        place=_place(keeper), created_by=user, notes=circumstances,
        data={"loss_type": Specimen.Status(status).label},
    )
    DeclarationItem.objects.create(declaration=declaration, specimen=part, quantity=quantity, document=document)
    return declaration


# --------------------------------------------------------------------------- transfers

@transaction.atomic
def start_transfer(*, keeper, user, lines: list[TransferLine], counterparty: Counterparty, transfer_date: date,
                   is_sale: bool = True) -> Declaration:
    """Prepare a cessione. Annex A → SCT3 (request art. 9.2 certificate; animals move only after it is issued).
    Annex B → seller declaration; transfer is completed immediately."""
    if not lines:
        raise ServiceError("Nessun esemplare selezionato.")
    annexes = {line.specimen.species.eu_annex for line in lines}
    if len(annexes) > 1:
        raise ServiceError("Non mischiare esemplari di All. A e All. B nella stessa cessione.")
    annex = annexes.pop()
    kind = Declaration.Kind.TRANSFER if annex == "A" else Declaration.Kind.SALE_B
    declaration = Declaration.objects.create(
        keeper=keeper, kind=kind, office=_office(keeper), event_date=transfer_date, counterparty=counterparty,
        place=_place(keeper), created_by=user, data={"is_sale": is_sale},
    )
    for line in lines:
        if line.specimen.keeper_id != keeper.pk or not line.specimen.is_alive:
            raise ServiceError(f"{line.specimen} non disponibile per la cessione.")
        part = split_lot(line.specimen, line.quantity)
        DeclarationItem.objects.create(
            declaration=declaration, specimen=part, quantity=line.quantity,
            document=line.document or part.current_document,
        )
    if kind == Declaration.Kind.SALE_B:
        complete_transfer(declaration=declaration, user=user, completed_on=transfer_date)
    return declaration


@transaction.atomic
def complete_transfer(*, declaration: Declaration, user, completed_on: date, certificate_number: str = "",
                      certificate_date: date | None = None, certificate_file=None) -> None:
    """Animals physically handed over: mark transferred, write scarico, link movement certificate."""
    if declaration.kind not in (Declaration.Kind.TRANSFER, Declaration.Kind.SALE_B):
        raise ServiceError("Non è una cessione.")
    keeper = declaration.keeper
    cert = None
    if certificate_number:
        cert = CitesDocument.objects.create(
            keeper=keeper, doc_type=CitesDocument.DocType.CERT_MOVE, number=certificate_number,
            issued_on=certificate_date, issuer=str(declaration.office or ""),
            file=certificate_file or "",
        )
    is_sale = declaration.data.get("is_sale", True)
    cp = declaration.counterparty
    for item in declaration.items.select_related("specimen"):
        sp = item.specimen
        if not sp.is_alive:
            continue
        sp.transferred_to = cp
        sp.save(update_fields=["transferred_to"])
        _close_status(sp, Specimen.Status.TRANSFERRED, completed_on)
        if cert:
            cert.specimens.add(sp)
        doc_label = cert.form_label if cert else (item.document.form_label if item.document else "")
        _register(keeper, user, sp, RegisterEntry.Direction.OUT,
                  RegisterEntry.Cause.SALE if is_sale else RegisterEntry.Cause.TRANSFER,
                  completed_on, item.quantity, counterparty=f"{cp.full_name} – {cp.full_address}" if cp else "",
                  document=doc_label)
    if cert:
        declaration.protocol_number = declaration.protocol_number or certificate_number
        declaration.protocol_date = declaration.protocol_date or certificate_date
    declaration.status = Declaration.Status.CLOSED
    declaration.save()


@transaction.atomic
def register_acquisition(*, keeper, user, species, quantity: int, acquired_on: date, counterparty: Counterparty | None,
                         sex: str = Specimen.Sex.UNKNOWN, birth_date: date | None = None, name: str = "",
                         marking_kind: str = "", marking_code: str = "", document: CitesDocument | None = None,
                         origin: str = Specimen.Origin.ACQUIRED) -> Specimen:
    sp = Specimen.objects.create(
        keeper=keeper, species=species, site=keeper.default_site, name=name, quantity=quantity, sex=sex,
        birth_date=birth_date, origin=origin, acquired_from=counterparty, acquired_on=acquired_on,
    )
    if marking_kind:
        check_microchip_free(keeper, marking_kind, marking_code)
        Marking.objects.create(specimen=sp, kind=marking_kind, code=marking_code)
    if document:
        document.specimens.add(sp)
    cause = RegisterEntry.Cause.INITIAL if origin == Specimen.Origin.PRE_EXISTING else RegisterEntry.Cause.PURCHASE
    _register(keeper, user, sp, RegisterEntry.Direction.IN, cause, acquired_on, quantity,
              counterparty=f"{counterparty.full_name} – {counterparty.full_address}" if counterparty else "",
              document=document.form_label if document else "")
    return sp


# --------------------------------------------------------------------------- marking

@transaction.atomic
def add_marking(*, keeper, user, specimen: Specimen, kind: str, code: str, manufacturer: str = "",
                applied_on: date | None = None, applied_by: str = "", notify: bool = True) -> Declaration | None:
    """Mark one animal. If the specimen is a lot, one animal is split off first."""
    check_microchip_free(keeper, kind, code)
    target = split_lot(specimen, 1) if specimen.quantity > 1 else specimen
    Marking.objects.create(specimen=target, kind=kind, code=code, manufacturer=manufacturer,
                           applied_on=applied_on or timezone.localdate(), applied_by=applied_by)
    if not notify:
        return None
    declaration = Declaration.objects.create(
        keeper=keeper, kind=Declaration.Kind.MARKING, office=_office(keeper),
        event_date=applied_on or timezone.localdate(), place=_place(keeper), created_by=user,
    )
    DeclarationItem.objects.create(declaration=declaration, specimen=target, quantity=1,
                                   document=target.current_document)
    return declaration


# --------------------------------------------------------------------------- status

@transaction.atomic
def mark_sent(declaration: Declaration, sent_on: date, channel: str):
    declaration.sent_on = sent_on
    declaration.channel = channel
    declaration.status = Declaration.Status.SENT
    declaration.save()


@transaction.atomic
def mark_protocolled(declaration: Declaration, number: str, on: date | None, create_document: bool = True):
    """Office answered with a protocol (e.g. 'DC_1234 (10.100-1)'): store it and link it to the specimens,
    so later forms (e.g. SCT5) can cite it."""
    declaration.protocol_number = number
    declaration.protocol_date = on
    declaration.status = Declaration.Status.PROTOCOLLED
    declaration.save()
    doc_type = {
        Declaration.Kind.BIRTH_A: CitesDocument.DocType.BIRTH_PROTOCOL,
        Declaration.Kind.BIRTH_B: CitesDocument.DocType.BIRTH_PROTOCOL,
        Declaration.Kind.DEATH: CitesDocument.DocType.DEATH_PROTOCOL,
    }.get(declaration.kind)
    if create_document and doc_type:
        doc = CitesDocument.objects.create(
            keeper=declaration.keeper, doc_type=doc_type, number=number, issued_on=on,
            issuer=str(declaration.office or ""),
        )
        doc.specimens.set([i.specimen for i in declaration.items.all()])
        if declaration.kind == Declaration.Kind.DEATH:
            for item in declaration.items.all():
                if item.document and not item.document.returned_on:
                    item.document.returned_on = declaration.sent_on or on
                    item.document.save(update_fields=["returned_on"])
        return doc
    return None


# --------------------------------------------------------------------------- deletion

def _reverse_register(entries, user, reason: str):
    """The register is append-only: cancel entries with opposite 'rettifica' entries."""
    for e in entries:
        if e.cause == RegisterEntry.Cause.CORRECTION or e.corrections.exists():
            continue
        RegisterEntry.objects.create(
            keeper=e.keeper, register_type=e.register_type,
            direction=RegisterEntry.Direction.OUT if e.direction == RegisterEntry.Direction.IN
            else RegisterEntry.Direction.IN,
            cause=RegisterEntry.Cause.CORRECTION, event_date=e.event_date, species=e.species, specimen=e.specimen,
            quantity=e.quantity, description=e.description, marking=e.marking, document=e.document,
            counterparty=e.counterparty, corrects=e, notes=f"Rettifica reg. n. {e.number}: {reason}"[:255],
            created_by=user,
        )


def _family(specimens):
    """Specimens plus every part split from them (recursively)."""
    out, todo = {}, list(specimens)
    while todo:
        sp = todo.pop()
        if sp.pk in out:
            continue
        out[sp.pk] = sp
        todo.extend(sp.splits.all())
    return list(out.values())


def _other_declarations(specimens, declaration):
    from .models import DeclarationItem

    return {i.declaration for i in DeclarationItem.objects.filter(specimen__in=specimens)
            .exclude(declaration=declaration).select_related("declaration")}


@transaction.atomic
def delete_declaration(declaration, user) -> str:
    """Delete a declaration of any status and undo what it did to the registry:
    births remove the animals they created, deaths / losses / transfers bring the animals back,
    register entries are cancelled with 'rettifica' entries, protocols created for it are removed.
    Refuses (ServiceError) when later events depend on it."""
    from django.db.models import Q

    from apps.importer.models import ImportedFile

    from .models import Declaration as D

    reason = f"eliminata pratica {declaration.get_kind_display()} del {declaration.event_date:%d/%m/%Y}"
    items = list(declaration.items.select_related("specimen"))
    specimens = [i.specimen for i in items]
    summary = []

    protocol = declaration.protocol_number
    if protocol:  # numbers are encrypted in the DB: compare after decryption
        candidates = CitesDocument.objects.filter(
            keeper=declaration.keeper, specimens__in=specimens,
            doc_type__in=[CitesDocument.DocType.BIRTH_PROTOCOL, CitesDocument.DocType.DEATH_PROTOCOL,
                          CitesDocument.DocType.CERT_MOVE],
        ).distinct()
        for doc in [d for d in candidates if d.number == protocol]:
            if doc.file and doc.file.name:
                transaction.on_commit(lambda s=doc.file.storage, n=doc.file.name: s.delete(n))
            doc.delete()

    if declaration.kind in (D.Kind.BIRTH_A, D.Kind.BIRTH_B):
        family = _family(specimens)
        later = _other_declarations(family, declaration)
        changed = [s for s in family if not s.is_alive]
        if later or changed:
            names = ", ".join(sorted({f"{d.get_kind_display()} del {d.event_date:%d/%m/%Y}" for d in later}))
            raise ServiceError("Gli esemplari di questa nascita hanno eventi successivi"
                               + (f" ({names})" if names else " (decessi, cessioni)")
                               + ": elimina prima quelle pratiche.")
        _reverse_register(RegisterEntry.objects.filter(specimen__in=family), user, reason)
        declaration.items.all().delete()
        n = sum(s.quantity for s in family)
        Specimen.objects.filter(pk__in=[s.pk for s in family]).delete()
        summary.append(f"rimossi {n} esemplari nati")

    elif declaration.kind in (D.Kind.DEATH, D.Kind.LOSS, D.Kind.TRANSFER, D.Kind.SALE_B):
        later = {d for d in _other_declarations(specimens, declaration)
                 if d.event_date >= declaration.event_date and d.kind not in (D.Kind.BIRTH_A, D.Kind.BIRTH_B)}
        if later:
            names = ", ".join(sorted(f"{d.get_kind_display()} del {d.event_date:%d/%m/%Y}" for d in later))
            raise ServiceError(f"Gli stessi esemplari compaiono in pratiche successive ({names}): elimina prima quelle.")
        _reverse_register(RegisterEntry.objects.filter(specimen__in=specimens, direction=RegisterEntry.Direction.OUT)
                          .filter(Q(event_date__gte=declaration.event_date)), user, reason)
        declaration.items.all().delete()
        restored = 0
        for sp in specimens:
            sp.refresh_from_db()
            sp.status, sp.status_date, sp.cause_of_death, sp.transferred_to = Specimen.Status.ALIVE, None, "", None
            sp.save()
            restored += sp.quantity
            parent = sp.split_from
            # rejoin the lot it was split from, unless the part has its own identity (marking, other events)
            if parent and parent.is_alive and not sp.markings.exists() and not sp.declaration_items.exists():
                parent.quantity += sp.quantity
                parent.save(update_fields=["quantity"])
                sp.delete()
        summary.append(f"{restored} esemplari tornati in carico")
    else:
        declaration.items.all().delete()

    for f in ImportedFile.objects.filter(declaration=declaration):
        docs = (f.parsed or {}).get("documents", [])
        for d in docs:
            if (d.get("result") or {}).get("declaration") == declaration.pk:
                d["result"] = {"status": "review", "message": "Pratica eliminata: da registrare di nuovo."}
        if docs:
            from apps.importer.autoapply import file_status

            f.status = file_status(f.parsed)
        else:
            f.status = ImportedFile.Status.PARSED
        f.declaration = None
        f.save(update_fields=["parsed", "status", "declaration", "updated_at"])

    files = [declaration.pdf] + [a.file for a in declaration.attachments.all()]
    for ff in files:
        if ff and ff.name:
            transaction.on_commit(lambda s=ff.storage, n=ff.name: s.delete(n))
    declaration.delete()
    return "Pratica eliminata" + (f": {', '.join(summary)}" if summary else "") + "."
