"""Signature stamping and identity-document attachment for generated declarations."""

import io

from PIL import Image, ImageChops, ImageOps
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# Signature area (x0, y0, x1, y1 in PDF points, origin bottom-left) on every page of the
# template-based forms: just above the "firma" line of the official layout.
SIGNATURE_BOXES = {
    "SCT1A": (345, 108, 555, 156),
    "SCT1B": (345, 144, 555, 190),
    "SCT5": (378, 331, 540, 376),
}


def prepare_signature(data: bytes) -> bytes:
    """Normalise an uploaded signature: transparent background, cropped to the ink, max 1200 px wide."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
    if img.width > 2400:
        img = img.resize((2400, max(1, round(img.height * 2400 / img.width))), Image.LANCZOS)
    # paper / white background -> transparent (keep any existing transparency)
    ink = img.convert("L").point(lambda v: 0 if v > 225 else 255)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), ink))
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    if img.width > 1200:
        img = img.resize((1200, max(1, round(img.height * 1200 / img.width))), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _fit(img_w, img_h, box):
    x0, y0, x1, y1 = box
    scale = min((x1 - x0) / img_w, (y1 - y0) / img_h)
    w, h = img_w * scale, img_h * scale
    return x0 + ((x1 - x0) - w) / 2, y0, w, h  # centred, sitting on the line


def stamp_signature(pdf: bytes, kind: str, signature_png: bytes) -> bytes:
    """Draw the signature in the form's signature box on every page (each page is one copy of the form)."""
    box = SIGNATURE_BOXES.get(kind)
    if not box or not signature_png:
        return pdf
    img = Image.open(io.BytesIO(signature_png))
    x, y, w, h = _fit(img.width, img.height, box)
    writer = PdfWriter(clone_from=io.BytesIO(pdf))
    for page in writer.pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        c.drawImage(ImageReader(io.BytesIO(signature_png)), x, y, w, h, mask="auto")
        c.save()
        page.merge_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _image_page(data: bytes) -> bytes:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 9)
    c.drawString(15 * mm, A4[1] - 12 * mm, "Copia del documento d'identità del dichiarante")
    box = (15 * mm, 15 * mm, A4[0] - 15 * mm, A4[1] - 20 * mm)
    x0, y0, x1, y1 = box
    scale = min((x1 - x0) / img.width, (y1 - y0) / img.height, 1.5)
    w, h = img.width * scale, img.height * scale
    jpeg = io.BytesIO()
    img.save(jpeg, "JPEG", quality=85)
    c.drawImage(ImageReader(io.BytesIO(jpeg.getvalue())), x0 + ((x1 - x0) - w) / 2, y1 - h, w, h)
    c.save()
    return buf.getvalue()


def readable_document(data: bytes, name: str) -> bool:
    """True if `data` is a PDF pypdf can read or an image PIL can open."""
    try:
        if data[:5] == b"%PDF-" or name.lower().endswith(".pdf"):
            return len(PdfReader(io.BytesIO(data)).pages) > 0
        Image.open(io.BytesIO(data)).verify()
        return True
    except Exception:
        return False


def append_document(pdf: bytes, attachment: bytes, name: str) -> bytes:
    """Concatenate the identity document (PDF pages, or an image laid out on an A4 page).
    An unreadable attachment is skipped rather than breaking the declaration."""
    if not attachment or not readable_document(attachment, name):
        return pdf
    extra = attachment if attachment[:5] == b"%PDF-" or name.lower().endswith(".pdf") else _image_page(attachment)
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf)))
    writer.append(PdfReader(io.BytesIO(extra)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
