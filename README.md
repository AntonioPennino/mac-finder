# 🍎 Mac Mini M1 Finder

Scraper automatico che cerca offerte di **Mac Mini M1 (16GB RAM / 512GB SSD)** su:
- [Vinted.it](https://www.vinted.it)
- [Wallapop.it](https://it.wallapop.com)
- [Subito.it](https://www.subito.it)
- [eBay.it](https://www.ebay.it)

Gira automaticamente **ogni 4 ore** tramite GitHub Actions e manda una **email** quando trova nuove offerte.

---

## ⚙️ Setup su GitHub Actions

### 1. Fai il fork / crea il repository

Carica questi file su un repository GitHub pubblico.

### 2. Aggiungi i GitHub Secrets

Vai su **Settings → Secrets and variables → Actions → New repository secret** e aggiungi:

| Nome Secret | Valore |
|---|---|
| `EMAIL_FROM` | La tua email Gmail (es. `tuaemail@gmail.com`) |
| `EMAIL_PASSWORD` | La tua [App Password Gmail](https://myaccount.google.com/apppasswords) (16 caratteri) |
| `EMAIL_TO` | L'email dove ricevere le notifiche (può essere uguale a `EMAIL_FROM`) |

> **Come ottenere l'App Password Gmail:**
> 1. Vai su [myaccount.google.com](https://myaccount.google.com) → Sicurezza
> 2. Abilita la **Verifica in due passaggi** (se non già fatto)
> 3. Cerca **Password per le app**
> 4. Crea una password per "Mac Mini Finder"
> 5. Copia i 16 caratteri nel secret `EMAIL_PASSWORD`

### 3. Abilita i permessi di write per Actions

Vai su **Settings → Actions → General → Workflow permissions** e seleziona:
- ✅ **Read and write permissions**

### 4. Trigger manuale (opzionale)

Puoi lanciare la ricerca subito andando su **Actions → 🍎 Mac Mini Finder Watch → Run workflow**.

---

## 🖥️ Uso in locale

```bash
# Installa le dipendenze
pip install -r requirements.txt
playwright install chromium

# Imposta le variabili d'ambiente (PowerShell)
$env:EMAIL_FROM     = "tuaemail@gmail.com"
$env:EMAIL_PASSWORD = "xxxx xxxx xxxx xxxx"
$env:EMAIL_TO       = "tuaemail@gmail.com"

# Esecuzione singola
python mac_mini_finder.py

# Modalità watch (ogni 4 ore, loop infinito)
python mac_mini_finder.py --watch

# Modalità watch con intervallo personalizzato
python mac_mini_finder.py --watch --hours 6
```

---

## 🔍 Filtri applicati

| Filtro | Cosa esclude |
|---|---|
| Chip sbagliato | M2, M2 Pro/Max, M3+, Intel i3/i5/i7/i9, DTK (A12Z) |
| RAM sbagliata | Annunci con 8GB esplicito |
| Storage sbagliato | Annunci con 256GB esplicito |
| Anni Intel | Mac Mini 2011–2019 (tutti Intel) |
| Model ID Intel | A1993, A1347, 8,1 |
| Rotti | Rotto, non funzionante, guasto, brick... |
| Ritiro a mano | Solo ritiro fuori dalla Campania |

---

## 📂 File generati

- `risultati_mac_mini.txt` — Tutte le offerte trovate nell'ultimo run
- `seen_urls.json` — URL già notificati (per evitare email doppie)

Entrambi vengono aggiornati automaticamente nel repository dal bot dopo ogni run.
