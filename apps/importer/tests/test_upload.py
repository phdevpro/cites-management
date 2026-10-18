import io
import threading
import zipfile
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.importer import services
from apps.importer.models import ImportBatch, ImportedFile
from apps.pdfforms.render import render_pdf


def _zip(files: dict) -> SimpleUploadedFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return SimpleUploadedFile("Archive.zip", buf.getvalue(), content_type="application/zip")


def _birth_pdf(n):
    return render_pdf("SCT1A", {"fields": {"place_date": "Udine 26/10/2024"},
                                "rows": [{"scientific_name": f"n{n} - TESTUDO HERMANNI", "birth_date": "18/10/2024"}]},
                      flatten=False)


@pytest.mark.django_db
def test_zip_upload_creates_batch_and_analyzes(client_logged, keeper, hermanni):
    archive = _zip({"2024/denuncia_nascita.pdf": _birth_pdf(9), "2023/altra.pdf": _birth_pdf(4),
                    "__MACOSX/._x.pdf": b"junk", "2024/note.txt": b"ignored"})
    resp = client_logged.post("/importa/", {"archive": archive, "label": "Primo import"})
    batch = ImportBatch.objects.get()
    assert resp.url == f"/importa/lotto/{batch.pk}/"
    files = list(batch.files.all())
    assert len(files) == 2 and {f.status for f in files} == {"parsed"}
    assert {f.year_hint for f in files} == {2023, 2024}
    assert {f.parsed["data"]["quantity"] for f in files} == {9, 4}
    page = client_logged.get(resp.url).content.decode()
    assert "Analisi in corso" not in page and "denuncia_nascita.pdf" in page


@pytest.mark.django_db
def test_bad_zip_shows_error(client_logged, keeper):
    bad = SimpleUploadedFile("Archive.zip", b"not a zip", content_type="application/zip")
    resp = client_logged.post("/importa/", {"archive": bad}, follow=True)
    assert "non è valido" in resp.content.decode()


@pytest.mark.django_db
def test_claim_and_requeue(keeper, user):
    batch = ImportBatch.objects.create(keeper=keeper)
    from django.core.files.base import ContentFile

    f, _ = services.add_file(batch, ContentFile(_birth_pdf(2), name="a.pdf"), "a.pdf", analyze_now=False)
    assert f.status == "pending"
    ImportedFile.objects.filter(pk=f.pk).update(status="processing")
    assert services.analyze_pending(batch.pk) == 0  # someone else is working on it
    assert services.requeue_stale(batch.pk) == 0  # not stale yet
    ImportedFile.objects.filter(pk=f.pk).update(updated_at=timezone.now() - timedelta(minutes=11))
    assert services.requeue_stale(batch.pk) == 1
    assert services.analyze_pending(batch.pk) == 1
    assert ImportedFile.objects.get(pk=f.pk).status == "parsed"


@pytest.mark.django_db(transaction=True)
def test_background_thread_analyzes_with_keys(keeper, user, keyring, settings):
    settings.IMPORT_BACKGROUND = True
    batch = ImportBatch.objects.create(keeper=keeper)
    from django.core.files.base import ContentFile

    services.add_file(batch, ContentFile(_birth_pdf(5), name="b.pdf"), "b.pdf", analyze_now=False)
    services.analyze_in_background(batch.pk, keyring)
    worker = next(t for t in threading.enumerate() if t.name == f"import-batch-{batch.pk}")
    worker.join(timeout=60)
    f = ImportedFile.objects.get()
    assert f.status == "parsed" and f.parsed["data"]["quantity"] == 5
