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


@pytest.mark.django_db
def test_imports_are_stored_encrypted(client_logged, keeper, settings):
    from pathlib import Path

    from django.db import connection

    archive = _zip({"2024/Rossi Mario denuncia.pdf": _birth_pdf(9)})
    client_logged.post("/importa/", {"archive": archive, "label": "Import di Mario Rossi"})
    with connection.cursor() as cur:
        cur.execute("SELECT original_name, original_path, text, parsed, sha256 FROM importer_importedfile")
        row = cur.fetchone()
        cur.execute("SELECT label FROM importer_importbatch")
        label = cur.fetchone()[0]
    assert all(v.startswith("enc1:") for v in row[:4]) and label.startswith("enc1:")
    assert "Rossi" not in "".join(row) + label and "HERMANNI" not in row[2]
    files = [p for p in Path(settings.MEDIA_ROOT).rglob("*") if p.is_file()]
    assert len(files) == 1 and files[0].read_bytes().startswith(b"CITESENC1") and "Rossi" not in files[0].name


def _stored_files(settings):
    from pathlib import Path

    return [p for p in Path(settings.MEDIA_ROOT).rglob("*") if p.is_file()]


@pytest.mark.django_db
def test_delete_selected_files_and_whole_batches(client_logged, keeper, user, settings, hermanni,
                                                 django_capture_on_commit_callbacks):
    archive = _zip({"a.pdf": _birth_pdf(1), "b.pdf": _birth_pdf(2), "c.pdf": _birth_pdf(3)})
    client_logged.post("/importa/", {"archive": archive, "label": "uno"})
    client_logged.post("/importa/", {"archive": _zip({"d.pdf": _birth_pdf(4)}), "label": "due"})
    first, second = ImportBatch.objects.order_by("pk")
    assert len(_stored_files(settings)) == 4
    index = client_logged.get("/importa/").content.decode()
    assert "Elimina tutti" in index and "uno" in index and "due" in index
    assert "Elimina tutto l&#x27;import" in client_logged.get(f"/importa/lotto/{first.pk}/").content.decode() or \
        "Elimina tutto l'import" in client_logged.get(f"/importa/lotto/{first.pk}/").content.decode()

    # register one file, then delete it with another: registered data must survive
    from apps.importer.forms import ReviewForm
    from apps.importer.views import _initial

    f = first.files.order_by("pk").first()
    form = ReviewForm(data={**{k: v for k, v in _initial(f).items() if v is not None},
                            "event_date": "2024-10-18"}, keeper=keeper)
    assert form.is_valid(), form.errors
    services.apply(f, form.cleaned_data, user)
    decl = ImportedFile.objects.get(pk=f.pk).declaration

    ids = list(first.files.order_by("pk").values_list("pk", flat=True)[:2])
    with django_capture_on_commit_callbacks(execute=True):
        resp = client_logged.post(f"/importa/lotto/{first.pk}/elimina/", {"ids": [str(i) for i in ids]})
    assert resp.url == f"/importa/lotto/{first.pk}/"
    assert first.files.count() == 1
    assert decl.attachments.count() == 1  # registered declaration keeps its own copy of the document

    with django_capture_on_commit_callbacks(execute=True):
        client_logged.post("/importa/elimina/", {"ids": [str(second.pk)]})
    assert list(ImportBatch.objects.all()) == [first]
    with django_capture_on_commit_callbacks(execute=True):
        client_logged.post("/importa/elimina/", {"all": "1"})
    assert not ImportBatch.objects.exists() and not ImportedFile.objects.exists()
    # only the declaration attachment is left on disk
    assert len(_stored_files(settings)) == 1


@pytest.mark.django_db
def test_cannot_delete_other_keepers_imports(client, keeper, user):
    from apps.accounts.models import Keeper, Membership
    from apps.vault import services as vault
    from conftest import make_vault_user, unlock_client

    batch = ImportBatch.objects.create(keeper=keeper)
    other_keeper = Keeper(first_name="A", last_name="B")
    dek = vault.new_keeper_key(other_keeper)
    other_keeper.save()
    other = make_vault_user("intruder")
    vault.share_with(Membership.objects.create(user=other, keeper=other_keeper), dek)
    unlock_client(client, other)
    assert client.post(f"/importa/lotto/{batch.pk}/elimina/", {"whole": "1"}).status_code == 404
    client.post("/importa/elimina/", {"all": "1"})
    assert ImportBatch.objects.filter(pk=batch.pk).exists()


@pytest.mark.django_db
def test_analysis_does_not_resurrect_deleted_file(keeper):
    from django.core.files.base import ContentFile

    batch = ImportBatch.objects.create(keeper=keeper)
    f, _ = services.add_file(batch, ContentFile(_birth_pdf(2), name="a.pdf"), "a.pdf", analyze_now=False)
    stale = ImportedFile.objects.get(pk=f.pk)
    ImportedFile.objects.filter(pk=f.pk).delete()
    services.analyze(stale)
    assert not ImportedFile.objects.filter(pk=f.pk).exists()


@pytest.mark.django_db
def test_review_moves_to_next_file_and_reports_errors(client_logged, keeper):
    from django.core.files.base import ContentFile

    batch = ImportBatch.objects.create(keeper=keeper)
    a, b, c = (services.add_file(batch, ContentFile(_birth_pdf(n), name=f"{n}.pdf"), f"{n}.pdf")[0] for n in (1, 2, 3))
    assert {f.status for f in (a, b, c)} == {"parsed"}

    # invalid submission: stays, and says why
    resp = client_logged.post(f"/importa/file/{b.pk}/", {"action": "document"}, follow=True)
    assert resp.redirect_chain == [] and "Non registrato, controlla" in resp.content.decode()

    skip = {"action": "skip"}
    assert client_logged.post(f"/importa/file/{b.pk}/", skip).url == f"/importa/file/{c.pk}/"  # next, not first
    assert client_logged.post(f"/importa/file/{c.pk}/", skip).url == f"/importa/file/{a.pk}/"  # wraps around
    assert client_logged.post(f"/importa/file/{a.pk}/", skip).url == f"/importa/lotto/{batch.pk}/"  # all done
