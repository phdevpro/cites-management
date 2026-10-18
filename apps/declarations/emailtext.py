"""Ready-to-send email (recipient, subject, body) to submit a declaration to the CITES office."""

from urllib.parse import quote

from apps.pdfforms.render import output_options

from .models import Declaration as D


def _species_summary(decl) -> str:
    groups: dict[str, int] = {}
    for item in decl.items.select_related("specimen__species"):
        name = item.specimen.species.scientific_name
        groups[name] = groups.get(name, 0) + item.quantity
    return ", ".join(f"{name} (n. {qty})" for name, qty in groups.items()) or "esemplari"


def build_email(decl) -> dict:
    keeper = decl.keeper
    office = decl.office or keeper.cites_office
    species = _species_summary(decl)
    when = f"{decl.event_date:%d/%m/%Y}"
    who = keeper.full_name or str(keeper)
    opts = output_options(decl)
    signed = opts["signature"] and bool(keeper.signature)
    id_in_pdf = opts["id_doc"] and bool(keeper.id_doc_file)

    subjects = {
        D.Kind.BIRTH_A: f"Denuncia di nascita in cattività (art. 8-bis L. 150/1992) - {species} - nati il {when}",
        D.Kind.BIRTH_B: f"Denuncia di nascita in cattività (art. 8-bis L. 150/1992) - {species} - nati il {when}",
        D.Kind.DEATH: f"Comunicazione di decesso (art. 5 c. 2 L. 150/1992) - {species} - {when}",
        D.Kind.TRANSFER: f"Richiesta certificato di spostamento (art. 9.2 Reg. CE 338/97) - {species}",
        D.Kind.SALE_B: f"Dichiarazione di cessione - {species} - {when}",
        D.Kind.LOSS: f"Comunicazione di smarrimento/fuga/furto - {species} - {when}",
        D.Kind.SITE_CHANGE: f"Comunicazione di variazione del luogo di detenzione - {species}",
        D.Kind.MARKING: f"Comunicazione di avvenuta marcatura - {species}",
    }
    intros = {
        D.Kind.BIRTH_A: f"con la presente si trasmette la denuncia di nascita in cattività (Modello SCT1/A) relativa a {species}, nati il {when}.",
        D.Kind.BIRTH_B: f"con la presente si trasmette la denuncia di nascita in cattività (Modello SCT1/B) relativa a {species}, nati il {when}.",
        D.Kind.DEATH: f"con la presente si comunica il decesso, avvenuto il {when}, dei seguenti esemplari: {species} (Modello SCT5).",
        D.Kind.TRANSFER: f"con la presente si trasmette la scheda informativa (Modello SCT3) per la richiesta del certificato di "
                         f"spostamento ai sensi dell'art. 9.2 del Reg. (CE) 338/97 relativo a {species}"
                         + (f", destinati a {decl.counterparty}" if decl.counterparty else "") + ".",
        D.Kind.SALE_B: f"con la presente si trasmette la dichiarazione di cessione relativa a {species}"
                       + (f" a favore di {decl.counterparty}" if decl.counterparty else "") + ".",
        D.Kind.LOSS: f"con la presente si comunica quanto avvenuto il {when} relativamente a {species}.",
        D.Kind.SITE_CHANGE: f"con la presente si comunica la variazione del luogo di detenzione di {species}.",
        D.Kind.MARKING: f"con la presente si comunica l'avvenuta marcatura di {species}.",
    }

    attachments = [f"{decl.get_kind_display()} compilata" + (" e firmata" if signed else " (da firmare)")]
    if id_in_pdf:
        attachments[0] += ", con copia del documento d'identità in coda"
    else:
        attachments.append("copia del documento d'identità del dichiarante")
    if decl.kind == D.Kind.TRANSFER:
        attachments += ["ricevuta del pagamento del diritto speciale di prelievo (cod. W802)",
                        "copia del documento d'identità del destinatario",
                        "copia dei documenti CITES degli esemplari"]
    notes = []
    if decl.kind == D.Kind.DEATH:
        notes.append("I certificati originali degli esemplari deceduti vengono restituiti come previsto dal modello.")

    office_name = office.name if office else "Servizio CITES territoriale"
    contact = ", ".join(p for p in [keeper.phone, keeper.email] if p)
    body = "\n".join([
        f"Spett.le {office_name},",
        "",
        f"il/la sottoscritto/a {who} " + intros.get(decl.kind, "trasmette la documentazione in allegato."),
        *([""] + notes if notes else []),
        "",
        "In allegato:",
        *[f"- {a}" for a in attachments],
        "",
        "Resto a disposizione per eventuali chiarimenti.",
        "",
        "Distinti saluti,",
        who,
        *([contact] if contact else []),
    ])
    to = (office.pec or office.email) if office else ""
    subject = subjects.get(decl.kind, decl.get_kind_display())
    mailto = f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)}"
    return {"to": to, "subject": subject, "body": body, "mailto": mailto, "office": office}
