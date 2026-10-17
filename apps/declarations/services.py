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
