"""Turn AI-read documents into registry records, without guessing.

Documents of a whole import are processed in chronological order (births before the replies
that acknowledge them, before the deaths that reference them). A document is applied
automatically only when the AI is confident and the match with existing records is unique;
otherwise it is left for the user with the reason. Every outcome is stored on the document
(parsed["documents"][i]["result"]).
"""

import re
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from apps.declarations import services as decl_services
from apps.declarations.models import Attachment, Declaration, FeeType, Payment
from apps.registry.models import CitesDocument, Counterparty, Marking, Specimen
from apps.species.models import Species

from .models import ImportedFile

KIND_ORDER = {"birth_declaration": 0, "transfer_request": 1, "death_declaration": 2, "marking_record": 3,
              "office_reply": 4, "movement_certificate": 5, "payment_receipt": 6, "identity_document": 7, "other": 8}
RELATED_KINDS = {"birth": ["SCT1A", "SCT1B"], "death": ["SCT5"], "transfer": ["SCT3", "CESSB"], "marking": ["MARK"]}
DOC_TYPE_FOR = {"birth": "dn", "death": "dd", "transfer": "art9", "marking": "other", "payment": "other", "other": "other"}


def _date(text):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _digits(text: str) -> set[str]:
    """Number groups of a protocol ('3519 (30.316-3)' -> {'3519', '30', '316'}) for fuzzy matching."""
    return {g for g in re.findall(r"\d+", text or "") if len(g) >= 2}


def _result(status, message, **objects):
    return {"status": status, "message": message, **{k: v for k, v in objects.items() if v is not None}}


class Applier:
    def __init__(self, batch, user):
        self.batch = batch
        self.keeper = batch.keeper
        self.user = user
        self.min_conf = getattr(settings, "AI_MIN_CONFIDENCE", 0.75)

    # ------------------------------------------------------------------ helpers
    def species(self, doc):
        name = doc.get("species", "")
        return Species.objects.filter(scientific_name__iexact=name).first() if name else None

    def attach(self, declaration, f, kind=Attachment.Kind.ORIGINAL):
        if declaration.attachments.filter(description=f.original_name, kind=kind).exists():
            return
        from .services import _attach

        _attach(declaration, f, kind)

    def mark_imported(self, declaration, doc, f):
        from .services import _status_fields

        signed = _date(doc.get("document_date")) or declaration.event_date
        _status_fields(declaration, {"signed_on": signed, "protocol_number": "", "protocol_date": None})
        self.attach(declaration, f)
        if doc.get("protocol_number"):
            decl_services.mark_protocolled(declaration, doc["protocol_number"], signed)

    def duplicate_declaration(self, kinds, species, quantity, event_date):
        for d in Declaration.objects.filter(keeper=self.keeper, kind__in=kinds, event_date=event_date):
            items = list(d.items.select_related("specimen"))
            if items and all(i.specimen.species_id == species.pk for i in items) and \
                    (not quantity or sum(i.quantity for i in items) == quantity):
                return d
        return None

    def counterparty(self, doc):
        name = doc.get("counterparty_name", "").strip()
        if not name:
            return None
        for cp in Counterparty.objects.filter(keeper=self.keeper):  # names are encrypted: compare in Python
            if cp.full_name.lower() == name.lower() or str(cp).lower() == name.lower():
                return cp
        first, _, last = name.partition(" ")
        return Counterparty.objects.create(keeper=self.keeper, first_name=first, last_name=last,
                                           address=doc.get("counterparty_address", "")[:200],
                                           notes="Creato automaticamente dall'import")

    def specimens_by_microchip(self, chips):
        wanted = set(chips)
        found = {}
        for m in Marking.objects.filter(specimen__keeper=self.keeper, kind=Marking.Kind.MICROCHIP).select_related("specimen"):
            code = re.sub(r"\D", "", m.code)
            if code in wanted:
                found[code] = m.specimen
        return found

    def lot_candidates(self, species, quantity, references, born_before=None):
        alive = Specimen.objects.filter(keeper=self.keeper, species=species, status=Specimen.Status.ALIVE)
        if born_before:
            alive = alive.exclude(birth_date__gt=born_before)
        alive = [s for s in alive if s.quantity >= max(quantity, 1)]
        refs = set().union(*[_digits(r) for r in references]) if references else set()
        if refs:
            by_ref = [s for s in alive if any(_digits(d.number) & refs for d in s.cites_documents.all())]
            if by_ref:
                return by_ref
        return alive

    # ------------------------------------------------------------------ handlers
    def birth_declaration(self, f, doc):
        species, born = self.species(doc), _date(doc.get("event_date"))
        if not species:
            return _result("review", f"Specie '{doc.get('species')}' non presente: aggiungila e rielabora.")
        if not (born and doc.get("quantity")):
            return _result("review", "Data di nascita o numero di nati non leggibili.")
        dup = self.duplicate_declaration(["SCT1A", "SCT1B"], species, doc["quantity"], born)
        if dup:
            self.attach(dup, f)
            return _result("duplicate", "Nascita già registrata.", declaration=dup.pk)
        res = decl_services.register_birth(
            keeper=self.keeper, user=self.user, species=species, birth_date=born,
            rows=[decl_services.NewbornSpec(quantity=doc["quantity"])], breeding_group=doc.get("breeding_group", ""),
        )
        if res.declaration:
            self.mark_imported(res.declaration, doc, f)
            return _result("created", f"Nascita di {doc['quantity']} × {species} del {born:%d/%m/%Y}.",
                           declaration=res.declaration.pk)
        return _result("created", f"Registrati {doc['quantity']} nati (specie senza denuncia).")

    def death_declaration(self, f, doc):
        species, died = self.species(doc), _date(doc.get("event_date")) or _date(doc.get("document_date"))
        qty = doc.get("quantity") or 1
        if not (species and died):
            return _result("review", "Specie o data del decesso non leggibili.")
        dup = self.duplicate_declaration(["SCT5"], species, qty, died)
        if dup:
            self.attach(dup, f)
            return _result("duplicate", "Decesso già registrato.", declaration=dup.pk)
        candidates = self.lot_candidates(species, qty, doc.get("references", []), born_before=died)
        if len(candidates) != 1:
            names = ", ".join(str(c) for c in candidates[:5]) or "nessuno"
            return _result("review", f"Non è chiaro da quale lotto/esemplare (candidati: {names}).")
        decl = decl_services.register_death(keeper=self.keeper, user=self.user, specimen=candidates[0],
                                            quantity=qty, death_date=died)
        if decl:
            self.mark_imported(decl, doc, f)
        return _result("created", f"Decesso di {qty} × {species} del {died:%d/%m/%Y} (da {candidates[0]}).",
                       declaration=decl.pk if decl else None)

    def _transfer_lines(self, doc, species, qty):
        chips = doc.get("microchips", [])
        if chips:
            found = self.specimens_by_microchip(chips)
            if len(found) != len(set(chips)) or not all(s.is_alive for s in found.values()):
                return None, "Microchip non trovati tra gli esemplari vivi."
            return [decl_services.TransferLine(specimen=s, quantity=1) for s in found.values()], ""
        candidates = self.lot_candidates(species, qty, doc.get("references", []))
        if len(candidates) != 1:
            return None, f"Esemplari da cedere non individuabili in modo univoco ({len(candidates)} lotti possibili)."
        return [decl_services.TransferLine(specimen=candidates[0], quantity=qty)], ""

    def transfer_request(self, f, doc):
        species = self.species(doc)
        when = _date(doc.get("event_date")) or _date(doc.get("document_date"))
        qty = doc.get("quantity") or len(doc.get("microchips", [])) or 1
        if doc.get("direction") == "in":
            return self.incoming(f, doc)
        if not (species and when):
            return _result("review", "Specie o data della cessione non leggibili.")
        cp = self.counterparty(doc)
        if cp is None:
            return _result("review", "Destinatario della cessione non leggibile.")
        lines, why = self._transfer_lines(doc, species, qty)
        if lines is None:
            return _result("review", why)
        decl = decl_services.start_transfer(keeper=self.keeper, user=self.user, lines=lines, counterparty=cp,
                                            transfer_date=when)
        self.mark_imported(decl, doc, f)
        return _result("created", f"Cessione di {qty} × {species} a {cp}.", declaration=decl.pk)

    def incoming(self, f, doc):
        species = self.species(doc)
        when = _date(doc.get("event_date")) or _date(doc.get("document_date"))
        if not (species and when):
            return _result("review", "Acquisizione: specie o data non leggibili.")
        cp = self.counterparty(doc)
        number = doc.get("certificate_number") or doc.get("protocol_number")
        cert = None
        if number:
            cert = CitesDocument.objects.create(keeper=self.keeper, doc_type=CitesDocument.DocType.CERT_MOVE,
                                                number=number, issued_on=_date(doc.get("document_date")),
                                                issuer=doc.get("office", ""))
        chips = doc.get("microchips", [])
        qty = len(chips) or doc.get("quantity") or 1
        created = []
        for chip in chips or [None]:
            sp = decl_services.register_acquisition(
                keeper=self.keeper, user=self.user, species=species, quantity=1 if chip else qty, acquired_on=when,
                counterparty=cp, marking_kind="microchip" if chip else "", marking_code=chip or "", document=cert)
            created.append(sp)
        return _result("created", f"Acquisizione di {qty} × {species}" + (f" da {cp}" if cp else "") + ".",
                       specimens=[s.pk for s in created])

    def _matching_declaration(self, relates, doc):
        kinds = RELATED_KINDS.get(relates)
        if not kinds:
            return []
        species = self.species(doc)
        reply_date = _date(doc.get("document_date")) or _date(doc.get("event_date"))
        qs = Declaration.objects.filter(keeper=self.keeper, kind__in=kinds)
        if reply_date:
            qs = qs.filter(event_date__lte=reply_date, event_date__gte=reply_date - timedelta(days=200))
        out = []
        for d in qs.order_by("-event_date"):
            items = list(d.items.select_related("specimen"))
            if species and items and not all(i.specimen.species_id == species.pk for i in items):
                continue
            if doc.get("quantity") and items and sum(i.quantity for i in items) != doc["quantity"]:
                continue
            out.append(d)
        if len(out) > 1:  # prefer the ones still waiting for a protocol
            waiting = [d for d in out if not d.protocol_number or d.kind in ("SCT3", "CESSB") and d.status != "closed"]
            out = waiting or out
        return out

    def office_reply(self, f, doc):
        relates = doc.get("relates_to", "other")
        number = doc.get("protocol_number") or doc.get("certificate_number")
        if relates == "payment" or not number:
            return self.archive_on_declaration(f, doc, relates)
        matches = self._matching_declaration(relates, doc)
        when = _date(doc.get("document_date"))
        if len(matches) == 1:
            decl = matches[0]
            if decl.kind in ("SCT3", "CESSB") and decl.status != Declaration.Status.CLOSED and doc.get("certificate_number"):
                decl_services.complete_transfer(declaration=decl, user=self.user, completed_on=when or decl.event_date,
                                                certificate_number=doc["certificate_number"], certificate_date=when)
            elif decl.protocol_number and _digits(decl.protocol_number) & _digits(number):
                self.attach(decl, f, Attachment.Kind.REPLY)
                return _result("duplicate", "Protocollo già registrato.", declaration=decl.pk)
            else:
                decl_services.mark_protocolled(decl, number, when)
            self.attach(decl, f, Attachment.Kind.REPLY)
            return _result("linked", f"Protocollo {number} collegato a: {decl.get_kind_display()} del "
                                     f"{decl.event_date:%d/%m/%Y}.", declaration=decl.pk)
        doc_obj = CitesDocument.objects.create(
            keeper=self.keeper, doc_type=DOC_TYPE_FOR.get(relates, "other"), number=number, issued_on=when,
            issuer=doc.get("office", ""), notes=doc.get("summary", ""))
        self._file_on_document(doc_obj, f)
        why = "nessuna pratica corrispondente" if not matches else f"{len(matches)} pratiche possibili"
        return _result("review", f"Documento {number} registrato ma non collegato ({why}).", document=doc_obj.pk)

    def movement_certificate(self, f, doc):
        if doc.get("direction") == "in":
            return self.incoming(f, doc)
        if not doc.get("certificate_number"):
            return self.office_reply(f, doc)
        open_transfers = [d for d in self._matching_declaration("transfer", doc) if d.status != Declaration.Status.CLOSED]
        when = _date(doc.get("document_date"))
        if len(open_transfers) == 1:
            decl = open_transfers[0]
            decl_services.complete_transfer(declaration=decl, user=self.user, completed_on=when or decl.event_date,
                                            certificate_number=doc["certificate_number"], certificate_date=when)
            self.attach(decl, f, Attachment.Kind.CERTIFICATE)
            return _result("linked", f"Certificato {doc['certificate_number']}: cessione completata.",
                           declaration=decl.pk)
        if not open_transfers:  # archive only has the certificate: build the transfer from it
            res = self.transfer_request(f, {**doc, "event_date": doc.get("event_date") or doc.get("document_date")})
            if res["status"] == "created":
                decl = Declaration.objects.get(pk=res["declaration"])
                decl_services.complete_transfer(declaration=decl, user=self.user, completed_on=when or decl.event_date,
                                                certificate_number=doc["certificate_number"], certificate_date=when)
                res["message"] += f" Certificato {doc['certificate_number']} registrato."
            return res
        return _result("review", f"Certificato {doc['certificate_number']}: {len(open_transfers)} cessioni possibili.")

    def payment_receipt(self, f, doc):
        paid = _date(doc.get("document_date")) or _date(doc.get("event_date"))
        amount = Decimal(str(doc.get("amount_eur") or 0)).quantize(Decimal("0.01"))
        if not (paid and amount > 0):
            return _result("archived", "Documento di pagamento senza importo/data (informativo).")
        if Payment.objects.filter(keeper=self.keeper, paid_on=paid, amount=amount).exists():
            return _result("duplicate", "Pagamento già registrato.")
        from django.core.files import File

        pay = Payment.objects.create(keeper=self.keeper, amount=amount, paid_on=paid,
                                     fee_type=FeeType.objects.filter(amount=amount).first(),
                                     reference=doc.get("protocol_number", ""), description=doc.get("summary", "")[:255])
        f.file.open("rb")
        try:
            pay.receipt.save(f.original_name, File(f.file, name=f.original_name), save=True)
        finally:
            f.file.close()
        return _result("created", f"Pagamento di € {amount} del {paid:%d/%m/%Y}.", payment=pay.pk)

    def marking_record(self, f, doc):
        return _result("review", "Marcatura: indica a quale esemplare applicarla "
                                 f"(microchip {', '.join(doc.get('microchips', [])) or 'non letto'}).")

    def archive_on_declaration(self, f, doc, relates):
        matches = self._matching_declaration(relates, doc) if relates in RELATED_KINDS else []
        if len(matches) == 1:
            self.attach(matches[0], f, Attachment.Kind.OTHER)
            return _result("linked", f"Allegato a: {matches[0].get_kind_display()} del "
                                     f"{matches[0].event_date:%d/%m/%Y}.", declaration=matches[0].pk)
        return _result("archived", doc.get("summary") or "Archiviato.")

    def identity_document(self, f, doc):
        return _result("archived", "Documento d'identità archiviato (non inviato all'AI).")

    def other(self, f, doc):
        return _result("archived", doc.get("summary") or "Archiviato.")

    def _file_on_document(self, doc_obj, f):
        from django.core.files import File

        f.file.open("rb")
        try:
            doc_obj.file.save(f.original_name, File(f.file, name=f.original_name), save=True)
        finally:
            f.file.close()

    # ------------------------------------------------------------------ driver
    def apply_doc(self, f, doc):
        if doc.get("type") not in ("identity_document", "other") and doc.get("confidence", 0) < self.min_conf:
            return _result("review", f"Lettura incerta (affidabilità {doc.get('confidence', 0):.0%}).")
        handler = getattr(self, doc.get("type", "other"), self.other)
        try:
            with transaction.atomic():
                return handler(f, doc)
        except decl_services.ServiceError as exc:
            return _result("review", str(exc))


def _sort_key(item):
    f, i, doc = item
    when = doc.get("event_date") or doc.get("document_date") or f"{f.year_hint or 9999}-12-31"
    return (when, KIND_ORDER.get(doc.get("type"), 9), f.pk, i)


def file_status(parsed) -> str:
    results = [d.get("result", {}).get("status") for d in parsed.get("documents", [])]
    if not results or any(r in (None, "review") for r in results):
        return ImportedFile.Status.PARSED
    if all(r == "archived" for r in results):
        return ImportedFile.Status.ARCHIVED
    return ImportedFile.Status.DONE


def auto_apply_batch(batch, user) -> dict:
    """Apply every not-yet-handled AI document of the batch. Returns counters by outcome."""
    applier = Applier(batch, user)
    files = list(batch.files.filter(status=ImportedFile.Status.PARSED))
    items = [(f, i, d) for f in files if (f.parsed or {}).get("ai")
             for i, d in enumerate(f.parsed.get("documents", [])) if not d.get("result") or
             d["result"].get("status") == "review"]
    counters: dict[str, int] = {}
    touched = {}
    for f, i, doc in sorted(items, key=_sort_key):
        f = touched.get(f.pk, f)
        res = applier.apply_doc(f, doc)
        f.parsed["documents"][i]["result"] = res
        counters[res["status"]] = counters.get(res["status"], 0) + 1
        if res.get("declaration") and not f.declaration_id:
            f.declaration_id = res["declaration"]
        touched[f.pk] = f
    for f in touched.values():
        f.status = file_status(f.parsed)
        f.save(update_fields=["parsed", "status", "declaration", "updated_at"])
    return counters
