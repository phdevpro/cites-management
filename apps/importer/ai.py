"""AI-assisted reading of archive documents through Regolo.ai (OpenAI-compatible, EU-hosted).

Pipeline per file:
1. every page is rendered/extracted locally;
2. identity-document pages are detected LOCALLY and never sent anywhere;
3. pages with a text layer use it; scanned pages go to the OCR model (deepseek-ocr-2);
4. the page texts go to the extraction model, which returns the list of documents found
   in the file (a PDF may contain several) as JSON validated against SCHEMA.

The AI only reads. Creating records is done by deterministic code (autoapply.py).
"""

import base64
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)

DOC_TYPES = [
    "birth_declaration",  # SCT1/A, SCT1/B
    "death_declaration",  # SCT5
    "transfer_request",  # SCT3 / scheda spostamento, dichiarazione di cessione
    "movement_certificate",  # certificato art. 9.2 / art. 10 rilasciato dall'ufficio
    "office_reply",  # lettera/protocollo del Nucleo CITES (presa d'atto nascita, decesso, ...)
    "payment_receipt",  # ricevuta diritto speciale di prelievo
    "marking_record",  # inserimento microchip / certificato veterinario di marcatura
    "identity_document",
    "other",
]

RELATES = ["birth", "death", "transfer", "marking", "payment", "other"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["documents"],
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "relates_to", "direction", "pages", "confidence", "species", "quantity", "event_date", "document_date",
                             "protocol_number", "certificate_number", "references", "microchips",
                             "counterparty_name", "counterparty_address", "amount_eur", "breeding_group",
                             "office", "summary"],
                "properties": {
                    "type": {"type": "string", "enum": DOC_TYPES},
                    "relates_to": {"type": "string", "enum": RELATES},
                    "direction": {"type": "string", "enum": ["out", "in", ""]},
                    "pages": {"type": "array", "items": {"type": "integer"}},
                    "confidence": {"type": "number"},
                    "species": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "event_date": {"type": "string"},
                    "document_date": {"type": "string"},
                    "protocol_number": {"type": "string"},
                    "certificate_number": {"type": "string"},
                    "references": {"type": "array", "items": {"type": "string"}},
                    "microchips": {"type": "array", "items": {"type": "string"}},
                    "counterparty_name": {"type": "string"},
                    "counterparty_address": {"type": "string"},
                    "amount_eur": {"type": "number"},
                    "breeding_group": {"type": "string"},
                    "office": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        }
    },
}

SYSTEM_PROMPT = """Sei un assistente che legge documenti CITES italiani di un allevatore privato di testuggini e altri
animali (L. 150/1992, Reg. CE 338/97 e 865/2006) per ricostruirne l'archivio.

Ricevi il testo di tutte le pagine di UN file (con il numero di pagina). Un file può contenere uno o più documenti
distinti: elenca ognuno separatamente con le sue pagine.

Tipi:
- birth_declaration: denuncia di nascita (Modello SCT1/A o SCT1/B) compilata dall'allevatore.
- death_declaration: comunicazione di decesso (Modello SCT5).
- transfer_request: scheda informativa spostamento/cessione (Modello SCT3) o dichiarazione di cessione.
- movement_certificate: certificato rilasciato dall'ufficio (es. numero IT/CE/AAAA/XX/NNNNN, art. 9.2 o art. 10).
- office_reply: lettera del Nucleo/Servizio CITES dei Carabinieri che prende atto o protocolla una denuncia,
  chiede integrazioni o pagamenti.
- payment_receipt: ricevuta di pagamento del diritto speciale di prelievo.
- marking_record: inserimento microchip, certificato del veterinario.
- identity_document: carta d'identità, patente, passaporto.
- other: qualsiasi altra cosa (moduli vuoti, istruzioni, avvisi generici).

Campi (stringa vuota, 0 o lista vuota se assenti; NON inventare):
- relates_to: a quale evento si riferisce il documento: birth (nascita), death (decesso), transfer (cessione,
  spostamento, vendita, acquisto), marking (marcatura), payment, other. Per una office_reply o un certificato indica
  l'evento di cui l'ufficio prende atto.
- direction: per cessioni/spostamenti/certificati, "out" se gli esemplari escono dal detentore indicato sotto,
  "in" se li riceve; stringa vuota negli altri casi.
- species: nome scientifico normalizzato "Genere specie" (es. "Testudo hermanni"; "T.h.", "TESTUDO HERMANNI" e simili
  diventano "Testudo hermanni").
- quantity: numero di esemplari a cui si riferisce il documento (es. "n 9", "n. 9 esemplari" = 9). Per una nascita la
  somma dei nati di tutte le righe. 0 se ignoto.
- event_date: data dell'evento in formato AAAA-MM-GG (nascita, decesso, spostamento). Per un modulo di decesso senza
  data esplicita usa la data di firma.
- document_date: data del documento/firma/lettera, AAAA-MM-GG.
- protocol_number: protocollo assegnato dall'ufficio a QUESTO documento (es. "3519 30/316-3", "Prot. 32/118-3").
- certificate_number: numero di certificato CITES rilasciato (es. "IT/CE/2024/TS/00271").
- references: protocolli o documenti PRECEDENTI citati (es. il protocollo della denuncia di nascita citato in un
  modulo di decesso, "PROT 750 DEL 1995" come gruppo riproduttore).
- microchips: codici di marcatura (15 cifre) presenti.
- counterparty_name / counterparty_address: altra persona coinvolta (acquirente, cedente, destinatario), solo nome e
  indirizzo; MAI codice fiscale o numeri di documenti d'identità.
- amount_eur: importo pagato.
- breeding_group: riferimento al gruppo riproduttore/genitori riportato nella denuncia di nascita.
- office: ufficio CITES destinatario/mittente (es. "Trieste").
- summary: una frase in italiano che descrive il documento.
- confidence: da 0 a 1, quanto sei sicuro di tipo e dati principali.
Il nome del file e la cartella possono contenere indizi (anno, "decesso", "DN" = denuncia di nascita, numero di
protocollo come "DC_3519 (30.316-3)")."""


class AIUnavailable(Exception):
    pass


@dataclass
class PageText:
    number: int
    text: str
    source: str  # text | ocr-ai | identity | empty
    identity: bool = False


@dataclass
class AIResult:
    pages: list = field(default_factory=list)
    documents: list = field(default_factory=list)
    model: str = ""
    warnings: list = field(default_factory=list)

    def as_dict(self):
        return {
            "ai": True, "model": self.model, "documents": self.documents, "warnings": self.warnings,
            "pages": [{"n": p.number, "source": p.source} for p in self.pages],
            "identity_pages": [p.number for p in self.pages if p.identity],
        }

    @property
    def text(self):
        return "\n\n".join(f"--- pagina {p.number} ---\n{p.text}" for p in self.pages if not p.identity)


def key_for(keeper=None) -> str:
    """The keeper's own Regolo key (stored encrypted on the profile); the server-wide
    REGOLO_API_KEY is only a fallback for self-hosted single-user installs."""
    from apps.vault.fields import Locked

    own = getattr(keeper, "ai_api_key", "") if keeper is not None else ""
    if own and not isinstance(own, Locked):
        return own
    return getattr(settings, "REGOLO_API_KEY", "")


def enabled(keeper=None) -> bool:
    return bool(key_for(keeper))


def client(api_key: str):
    if not api_key:
        raise AIUnavailable("Chiave Regolo.ai non impostata.")
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url=settings.REGOLO_BASE_URL, timeout=180, max_retries=3)


# --------------------------------------------------------------------------- local page handling

IDENTITY_MARKERS = re.compile(
    r"carta\s+d.?identit|identity\s+card|passaporto|passport|patente\s+di\s+guida|driving\s+licen|"
    r"repubblica\s+italiana.{0,80}(comune|cognome)|[A-Z<]{5,}<<[A-Z<]+|ministero\s+dell.interno",
    re.I | re.S,
)


def looks_like_identity(text: str) -> bool:
    return bool(IDENTITY_MARKERS.search(text or ""))


def _local_ocr(png: bytes) -> str:
    """Quick local OCR only to spot identity documents before anything leaves the server."""
    if not shutil.which("tesseract"):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "p.png"
        img.write_bytes(png)
        try:
            res = subprocess.run(["tesseract", str(img), "stdout", "-l", "ita+eng", "--psm", "3"],
                                 capture_output=True, timeout=90)
            return res.stdout.decode(errors="replace")
        except (OSError, subprocess.SubprocessError):
            return ""


def render_pages(path: Path, max_pages: int) -> list[tuple[int, bytes, str]]:
    """[(page number, PNG bytes, text layer)] for PDFs and images."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        import pdfplumber

        out = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages], start=1):
                text = page.extract_text() or ""
                buf = io.BytesIO()
                page.to_image(resolution=150).original.convert("RGB").save(buf, "PNG")
                out.append((i, buf.getvalue(), text))
        return out
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((2000, 2000))
        buf = io.BytesIO()
        img.save(buf, "PNG")
    return [(1, buf.getvalue(), "")]


def ocr_page_remote(png: bytes, api_key: str) -> str:
    resp = client(api_key).chat.completions.create(
        model=settings.AI_OCR_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Convert the document to markdown."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode(),
                                                "format": "image/png"}},
        ]}],
        extra_body={"skip_special_tokens": True},
    )
    return (resp.choices[0].message.content or "").strip()


def read_pages(path: Path, form_text: str = "", api_key: str = "") -> list[PageText]:
    pages = []
    for number, png, text in render_pages(path, settings.AI_MAX_PAGES):
        if len(text.strip()) >= 80:
            identity = looks_like_identity(text)
            pages.append(PageText(number, "" if identity else text, "identity" if identity else "text", identity))
            continue
        local = _local_ocr(png)
        if looks_like_identity(local):
            pages.append(PageText(number, "", "identity", True))  # never sent to the AI
            continue
        pages.append(PageText(number, ocr_page_remote(png, api_key), "ocr-ai"))
    if form_text and pages:
        pages[0].text = f"[campi del modulo compilato]\n{form_text}\n\n{pages[0].text}"
    return pages


# --------------------------------------------------------------------------- extraction

def extract_documents(pages: list[PageText], filename: str, path_hint: str, keeper_name: str = "",
                      api_key: str = "") -> list[dict]:
    readable = [p for p in pages if not p.identity and p.text.strip()]
    if not readable:
        return []
    body = "\n\n".join(f"--- pagina {p.number} ---\n{p.text[:15000]}" for p in readable)
    who = f"Detentore che archivia i documenti: {keeper_name}\n" if keeper_name else ""
    user = f"{who}File: {path_hint or filename}\n\n{body}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
    c = client(api_key)
    try:
        resp = c.chat.completions.create(
            model=settings.AI_EXTRACT_MODEL, messages=messages, max_tokens=8000, temperature=0,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "cites_documents", "strict": True, "schema": SCHEMA}},
        )
    except Exception as exc:  # some models only honor json_object
        from openai import BadRequestError

        if not isinstance(exc, BadRequestError):
            raise
        messages[0]["content"] += "\n\nRispondi SOLO con JSON conforme a questo schema:\n" + json.dumps(SCHEMA)
        resp = c.chat.completions.create(model=settings.AI_EXTRACT_MODEL, messages=messages, max_tokens=8000,
                                         temperature=0, response_format={"type": "json_object"})
    content = resp.choices[0].message.content or "{}"
    data = json.loads(_strip_fences(content))
    return [_clean(d) for d in data.get("documents", []) if isinstance(d, dict)]


def _strip_fences(text: str) -> str:
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else "{}"


def _clean(d: dict) -> dict:
    out = {k: d.get(k) for k in SCHEMA["properties"]["documents"]["items"]["properties"]}
    out["type"] = out["type"] if out["type"] in DOC_TYPES else "other"
    out["relates_to"] = out.get("relates_to") if out.get("relates_to") in RELATES else "other"
    out["direction"] = out.get("direction") if out.get("direction") in ("out", "in") else ""
    for k in ("species", "event_date", "document_date", "protocol_number", "certificate_number",
              "counterparty_name", "counterparty_address", "breeding_group", "office", "summary"):
        out[k] = str(out.get(k) or "").strip()
    for k in ("references", "microchips"):
        out[k] = [str(x).strip() for x in (out.get(k) or []) if str(x).strip()]
    out["pages"] = [int(x) for x in (out.get("pages") or []) if str(x).isdigit()]
    try:
        out["quantity"] = max(0, int(out.get("quantity") or 0))
    except (TypeError, ValueError):
        out["quantity"] = 0
    try:
        out["amount_eur"] = float(out.get("amount_eur") or 0)
    except (TypeError, ValueError):
        out["amount_eur"] = 0.0
    try:
        out["confidence"] = min(1.0, max(0.0, float(out.get("confidence") or 0)))
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    out["microchips"] = [re.sub(r"\D", "", m) for m in out["microchips"] if len(re.sub(r"\D", "", m)) == 15]
    for k in ("event_date", "document_date"):
        if out[k] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", out[k]):
            out[k] = ""
    if out["type"] == "identity_document":  # never keep personal data from IDs
        out.update(counterparty_name="", counterparty_address="", summary="Documento d'identità")
    return out


class ExtractionFailed(Exception):
    """Pages were read (OCR done) but the extraction model failed: callers can reuse result.pages."""

    def __init__(self, result, cause):
        super().__init__(explain(cause))
        self.result = result


def analyze_file(path: Path, filename: str, path_hint: str, form_text: str = "", keeper_name: str = "",
                 api_key: str = "") -> AIResult:
    result = AIResult(model=settings.AI_EXTRACT_MODEL)
    try:
        result.pages = read_pages(path, form_text, api_key)
    except Exception as exc:
        raise AIUnavailable(explain(exc)) from exc
    if result.pages and all(p.identity for p in result.pages):
        result.documents = [{**_clean({"type": "identity_document", "confidence": 1}),
                             "pages": [p.number for p in result.pages]}]
        return result
    try:
        result.documents = extract_documents(result.pages, filename, path_hint, keeper_name, api_key)
    except Exception as exc:
        raise ExtractionFailed(result, exc) from exc
    ids = [p.number for p in result.pages if p.identity]
    if ids:
        result.documents.append({**_clean({"type": "identity_document", "confidence": 1}), "pages": ids})
        result.warnings.append(f"Pagine {ids}: documento d'identità, archiviato senza invio all'AI.")
    return result


def explain(exc: Exception) -> str:
    """Human message for Regolo errors (e.g. key not enabled for a model)."""
    text = str(exc)
    m = re.search(r"can only access models=\[([^\]]*)\]\. Tried to access ([\w.\-]+)", text)
    if m:
        return (f"la chiave Regolo non è abilitata al modello {m.group(2)} (abilitati: {m.group(1)}): "
                f"aggiungilo ai modelli consentiti della chiave nella dashboard di Regolo")
    if "401" in text or "Unauthorized" in text or "invalid" in text.lower() and "key" in text.lower():
        return "chiave Regolo non valida o revocata"
    if "429" in text:
        return "limite di utilizzo Regolo raggiunto, riprova più tardi"
    return text[:300]


def check_key(api_key: str) -> list[str]:
    """Try both configured models with a minimal request. Empty list = all good."""
    problems = []
    try:
        c = client(api_key)
    except AIUnavailable as exc:
        return [str(exc)]
    blank = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (64, 64), "white").save(blank, "PNG")
    probes = [
        (settings.AI_OCR_MODEL, [{"role": "user", "content": [
            {"type": "text", "text": "Free OCR."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(blank.getvalue()).decode(),
                                                "format": "image/png"}}]}]),
        (settings.AI_EXTRACT_MODEL, [{"role": "user", "content": "Rispondi solo: ok"}]),
    ]
    for model, messages in probes:
        try:
            c.chat.completions.create(model=model, messages=messages, max_tokens=5)
        except Exception as exc:
            problems.append(f"{model}: {explain(exc)}")
    return problems
