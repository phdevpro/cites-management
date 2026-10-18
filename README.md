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
- **Lettura automatica con AI (facoltativa, Regolo.ai – UE)**: con `REGOLO_API_KEY` ogni pagina viene letta
  (OCR `deepseek-ocr-2` per le scansioni, testo diretto per i PDF), il modello `qwen3.5-122b` riconosce i documenti
  contenuti in ogni file (anche più di uno per PDF) e l'app crea in automatico nascite, decessi, cessioni, protocolli
  e pagamenti, in ordine cronologico, solo quando la corrispondenza è univoca; il resto va in revisione.
  Le pagine dei documenti d'identità sono riconosciute in locale e non vengono mai inviate.
  Verifica configurazione e modelli: `docker exec cites_web python manage.py ai_check`.
- **Registro di carico e scarico** (D.M. 8/1/2002) automatico e immodificabile (solo rettifiche), export PDF/XLSX.
- **Scadenze**: denuncia nascita 10 gg, estremi marcatura 45 gg, microchip Testudo entro 1 anno, risposte mancanti,
  documento d'identità in scadenza, specie passate in All. A (90 gg). Promemoria email: `manage.py send_reminders`.
- **Multi-utente / multi-detentore** con ruoli (titolare, collaboratore, sola lettura).
- Diritti speciali di prelievo (W802, U669, Y121, P048, Q840) e pagamenti con ricevute.
- Sincronizzazione allegati/appendici da Species+ (`manage.py sync_speciesplus`, richiede `SPECIESPLUS_TOKEN`).

## Cifratura dei dati personali

Ogni profilo detentore ha una propria **chiave dati** (AES-256-GCM). Ogni utente ha una **coppia di chiavi** X25519:
la chiave privata è salvata solo cifrata, con la **passphrase di cifratura** dell'utente (scrypt) e con una
**chiave di recupero** mostrata una sola volta alla configurazione. La chiave dati del profilo è sigillata con la
chiave pubblica di ogni membro, così il titolare può condividere l'accesso senza conoscere la passphrase altrui.

- Dopo il login si inserisce la passphrase (distinta dalla password di accesso); le chiavi sbloccate restano
  in un cookie cifrato legato alla sessione (12 ore, `VAULT_UNLOCK_MAX_AGE`), mai nel database. Menu 🔓 → *Blocca dati*.
- **Cifrati**: anagrafiche (nomi, codice fiscale, date di nascita, indirizzi, telefoni, email, documenti d'identità),
  controparti, nomi e note degli esemplari, microchip/anelli, numeri di protocollo e certificati, dati dei moduli,
  testo estratto dagli import, storico modifiche e **tutti i file** (contenuto cifrato, nomi casuali).
- **In chiaro**, per scadenze, promemoria e registro: date degli eventi, specie, quantità, stati, tipi di pratica,
  username ed email di accesso. Le email di promemoria indicano solo il numero di scadenze.
- Senza passphrase **e** chiave di recupero i dati non sono recuperabili da nessuno, amministratore compreso.
- Collaboratori: devono prima configurare la propria cifratura; poi il titolare li aggiunge da *Dati detentore*.
- Aggiornamento da una versione senza cifratura: al primo accesso il titolare configura la passphrase e conferma
  *Cifra profilo*; dati, storico e file esistenti vengono riscritti cifrati.

## Avvio

```bash
uv sync
cp .env.example .env            # imposta DJANGO_SECRET_KEY in produzione
uv run python manage.py migrate
uv run python manage.py load_initial_data   # specie, diritti, uffici CITES
uv run python manage.py createsuperuser     # oppure: seed_demo (passphrase demo = DEMO_PASSWORD)
uv run python manage.py runserver
```

OCR delle scansioni (facoltativo, Fedora): `sudo dnf install tesseract tesseract-langpack-ita`.

Import di un'intera cartella di archivio per il detentore con id 1, poi verifica da *Importa*:

```bash
uv run python manage.py import_archive "CITES Denuncia Tartarughe" --keeper 1 --user <username>
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

## Portainer + Traefik

Stack pronto in [`deploy/portainer-stack.yml`](deploy/portainer-stack.yml), pensato per un Traefik già attivo
sulla rete esterna `letsencrypt` (entrypoint `websecure`, certresolver `cloudflare`).

| Servizio | Ruolo |
|---|---|
| `cites-web` | App (immagine GHCR), esposta da Traefik su `CITES_HOST` |
| `cites-reminders` | Invia ogni giorno le email di scadenza (richiede `EMAIL_*`) |
| `cites-db` | Postgres 16 (volume `cites-db-data`) |
| `cites-db-backup` | Dump notturno alle 03:00 in `DBBK_LOCATION` (7 giorni, 4 settimane, 6 mesi) |

I file caricati stanno nel volume `cites-media`.

1. Sul server Docker dove gira Portainer (via SSH, non dal tuo PC) crea la cartella dei backup:
   ```bash
   sudo mkdir -p /srv/cites/db-backups
   ```
2. In Portainer: **Stacks → Add stack → Repository**
   - Repository URL: `https://github.com/phdevpro/cites-management`
   - Reference: `refs/heads/main`
   - Compose path: `deploy/portainer-stack.yml`
3. In **Environment variables** usa *Load variables from .env file* con
   [`deploy/stack.env.example`](deploy/stack.env.example) e imposta almeno:
   - `CITES_HOST` (es. `cites.tuodominio.it`, il record DNS deve puntare a Traefik)
   - `DJANGO_SECRET_KEY`: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`
   - `DB_PASSWORD`
   - `DBBK_LOCATION` (la cartella del punto 1)

   Portainer salva le variabili come `stack.env`, il file letto dallo stack.
4. **Deploy the stack**, poi crea l'amministratore:
   ```bash
   docker exec -it cites_web python manage.py createsuperuser
   ```
5. Accedi su `https://CITES_HOST`, crea il profilo detentore e imposta l'ufficio CITES di riferimento.

**Aggiornamenti:** nello stack, *Pull and redeploy* con *Re-pull image* attivo.

**Backup:** i dump di Postgres sono in `DBBK_LOCATION`. Il volume `cites-media` (documenti caricati) va incluso
nel backup dell'host: Portainer lo nomina con il prefisso dello stack, es. `cites_cites-media`.
Ripristino: i dump più recenti sono in `DBBK_LOCATION/last/` (formato *custom* di Postgres); vanno caricati con
`pg_restore` dentro `cites_postgres` a stack fermo, seguendo la documentazione di `prodrigestivill/postgres-backup-local`.

**Note:**
- Nei middleware Traefik si usa `customFrameOptionsValue=SAMEORIGIN` al posto di `frameDeny`, altrimenti
  l'anteprima PDF dentro l'app resta vuota.
- Lo stack non pubblica porte sulla LAN: i cookie sono solo HTTPS. Per l'accesso diretto in HTTP aggiungi
  `ports: ["8000:8000"]` a `cites-web` e imposta `DJANGO_SECURE_COOKIES=0` (sconsigliato).
- Per fissare una versione invece di `latest` imposta `CITES_VERSION` (es. `sha-422cc65`).

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

## Licenza

Progetto personale open source, senza scopo di lucro, rilasciato con licenza [MIT](LICENSE).
Chi installa una propria copia ne è l'unico gestore e responsabile; i Termini e l'Informativa privacy
inclusi si configurano con le variabili `LEGAL_*` (vedi `deploy/stack.env.example`).
