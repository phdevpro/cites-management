# CITES Manager

Django app per detentori/allevatori italiani di specie CITES (es. *Testudo hermanni*): registro esemplari,
compilazione automatica dei moduli per il Servizio CITES dei Carabinieri, import dell'archivio di denunce
precedenti, scadenze e registro di carico/scarico.

## Funzionalità

- **Moduli ufficiali compilati automaticamente** (dati detentore, esemplari, genitori, documenti CITES):
  - SCT1/A denuncia di nascita All. A (campi del PDF ufficiale) · SCT1/B nascita All. B (sovrastampa sul modello)
  - SCT5 comunicazione di decesso (cita e segna come restituiti i certificati)
  - SCT3 scheda spostamento/cessione All. A (richiesta certificato art. 9.2)
  - Dichiarazione di cessione All. B · comunicazioni di smarrimento/fuga/furto, cambio sito, marcatura
  - Editor dei campi prima della stampa, righe in eccesso → copie aggiuntive del modulo, busta, pacchetto ZIP con checklist
- **Esemplari e lotti**: i neonati non marcati si registrano come lotto ("n. 9 – Testudo hermanni"), poi si separano
  per decesso, cessione o microchip. Genealogia, marcature, documenti, storico modifiche.
- **Flusso pratiche**: bozza → PDF → inviata (PEC/raccomandata) → protocollata (il protocollo diventa documento CITES
  collegato agli esemplari) → chiusa. Cessioni All. A: gli esemplari restano in carico fino al certificato.
- **Import archivio**: PDF compilati (lettura campi AcroForm), PDF testuali, scansioni/immagini (OCR con Tesseract
  se installato), nomi file delle risposte (`DC_1234 (10.100-1) DN n. 9 Testudo hermanni.pdf`), ZIP per cartelle/anno,
  XLSX di esemplari. Ogni file passa da una schermata di verifica prima di essere registrato.
- **Registro di carico e scarico** (D.M. 8/1/2002) automatico e immodificabile (solo rettifiche), export PDF/XLSX.
- **Scadenze**: denuncia nascita 10 gg, estremi marcatura 45 gg, microchip Testudo entro 1 anno, risposte mancanti,
  documento d'identità in scadenza, specie passate in All. A (90 gg). Promemoria email: `manage.py send_reminders`.
- **Multi-utente / multi-detentore** con ruoli (titolare, collaboratore, sola lettura).
- Diritti speciali di prelievo (W802, U669, Y121, P048, Q840) e pagamenti con ricevute.
- Sincronizzazione allegati/appendici da Species+ (`manage.py sync_speciesplus`, richiede `SPECIESPLUS_TOKEN`).

## Avvio

```bash
uv sync
cp .env.example .env            # imposta DJANGO_SECRET_KEY in produzione
uv run python manage.py migrate
uv run python manage.py load_initial_data   # specie, diritti, uffici CITES
uv run python manage.py createsuperuser     # oppure: seed_demo per dati di esempio
uv run python manage.py runserver
```

OCR delle scansioni (facoltativo, Fedora): `sudo dnf install tesseract tesseract-langpack-ita`.

Import di un'intera cartella di archivio per il detentore con id 1, poi verifica da *Importa*:

```bash
uv run python manage.py import_archive "CITES Denuncia Tartarughe" --keeper 1
```

Promemoria giornalieri (cron): `uv run python manage.py send_reminders`.

## Docker / GHCR

Ogni push su `main` esegue i test e pubblica l'immagine `ghcr.io/phdevpro/cites-management:latest`
(anche `sha-…` e, per i tag `v*`, la versione). Sul server:

```bash
curl -O https://raw.githubusercontent.com/phdevpro/cites-management/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/phdevpro/cites-management/main/.env.example
# modifica .env: DJANGO_DEBUG=0, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS,
# DJANGO_CSRF_TRUSTED_ORIGINS=https://tuo-dominio, POSTGRES_PASSWORD
docker compose up -d
docker compose exec web python manage.py createsuperuser
```

L'app ascolta su `127.0.0.1:8000`: esporla tramite un reverse proxy HTTPS (Caddy, Traefik, nginx).
I file caricati (documenti d'identità, certificati) stanno nel volume `media` e sono serviti solo agli utenti
del detentore proprietario. OCR (Tesseract ita) è incluso nell'immagine.
Aggiornamento: `docker compose pull && docker compose up -d`. Backup: volume `pgdata` + volume `media`.

## Test

```bash
uv run pytest
```

## Note

- I modelli PDF in `apps/pdfforms/templates_pdf/` sono le versioni più recenti disponibili nell'archivio (2021–2025),
  ripulite dai dati personali (un test lo verifica). Il sito carabinieri.it non pubblica più la modulistica:
  verificare con il proprio Nucleo CITES eventuali nuove versioni.
- Termini e importi sono configurabili (`CITES_DEADLINES` in `config/settings.py`, tabella diritti in admin) e vanno
  verificati con l'ufficio competente.
- La cartella `CITES Denuncia Tartarughe/` e `media/` contengono documenti personali e sono escluse da git.
