"""Text extraction from archive documents: AcroForm values, PDF text layer, OCR fallback."""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

PDF_EXT = {".pdf"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
SHEET_EXT = {".xlsx"}
MIN_TEXT_CHARS = 80


@dataclass
class Extraction:
    text: str = ""
    form_fields: dict = field(default_factory=dict)
    method: str = ""  # acroform | text | ocr | none
    pages: int = 0
    warnings: list = field(default_factory=list)


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_image(path: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        langs = "ita+eng" if _has_lang("ita") else "eng"
        subprocess.run(["tesseract", str(path), str(out), "-l", langs], check=True, capture_output=True, timeout=180)
        return (out.with_suffix(".txt")).read_text(errors="replace")


def _has_lang(lang: str) -> bool:
    try:
        res = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20)
        return lang in res.stdout.split()
    except (OSError, subprocess.SubprocessError):
        return False


def _ocr_pdf(path: Path, max_pages: int = 4) -> str:
    import pdfplumber

    texts = []
    with pdfplumber.open(path) as pdf, tempfile.TemporaryDirectory() as tmp:
        for i, page in enumerate(pdf.pages[:max_pages]):
            img_path = Path(tmp) / f"p{i}.png"
            page.to_image(resolution=300).original.save(img_path)
            texts.append(_ocr_image(img_path))
    return "\n".join(texts)


def _pdftotext(path: Path) -> str:
    if not shutil.which("pdftotext"):
        return ""
    try:
        res = subprocess.run(["pdftotext", "-layout", "-l", "6", str(path), "-"], capture_output=True, timeout=60)
        return res.stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _acroform_values(path: Path) -> dict:
    from pypdf import PdfReader

    try:
        fields = PdfReader(str(path)).get_fields() or {}
    except Exception:
        return {}
    return {name: str(f.get("/V")) for name, f in fields.items() if f.get("/V") not in (None, "")}


def extract(path: Path) -> Extraction:
    path = Path(path)
    ext = path.suffix.lower()
    result = Extraction()
    if ext in PDF_EXT:
        import pdfplumber

        result.form_fields = _acroform_values(path)
        try:
            with pdfplumber.open(path) as pdf:
                result.pages = len(pdf.pages)
                result.text = "\n".join((p.extract_text(layout=False) or "") for p in pdf.pages[:6])
        except Exception as exc:
            result.warnings.append(f"Lettura PDF fallita: {exc}")
        poppler = _pdftotext(path)
        if len(poppler.strip()) > len(result.text.strip()):
            # pdftotext also renders annotation/Fill&Sign text that pdfplumber skips
            result.text = poppler
        if result.form_fields:
            result.method = "acroform"
        elif len(result.text.strip()) >= MIN_TEXT_CHARS:
            result.method = "text"
        elif ocr_available():
            try:
                result.text = _ocr_pdf(path)
                result.method = "ocr"
            except Exception as exc:
                result.warnings.append(f"OCR fallito: {exc}")
                result.method = "none"
        else:
            result.method = "none"
            result.warnings.append("Documento scansionato: installare tesseract per l'OCR, oppure inserire i dati a mano.")
    elif ext in IMAGE_EXT:
        result.pages = 1
        if ocr_available():
            try:
                result.text = _ocr_image(path)
                result.method = "ocr"
            except Exception as exc:
                result.warnings.append(f"OCR fallito: {exc}")
                result.method = "none"
        else:
            result.method = "none"
            result.warnings.append("Immagine: installare tesseract per l'OCR, oppure inserire i dati a mano.")
    else:
        result.method = "none"
        result.warnings.append(f"Formato {ext} non gestito dall'estrazione testo.")
    return result
