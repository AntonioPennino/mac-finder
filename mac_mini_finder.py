#!/usr/bin/env python3
"""
Mac Mini Finder - Cerca Mac Mini M1 16GB/512GB su Vinted, Wallapop, Subito ed eBay.it.
Filtra varianti sbagliate (M2, Intel i3/i5/i7/i9, 8GB RAM, 256GB storage) e annunci sospetti.
Esclude ritiro-a-mano fuori dalla Campania.

USO:
  python mac_mini_finder.py                 # esecuzione singola
  python mac_mini_finder.py --watch         # modalità watch (default: ogni 4 ore)
  python mac_mini_finder.py --watch --hours 6
"""

import sys
import io

# Forza output UTF-8 su Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import time
import re
import random
import json
import os
import argparse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Set
from datetime import datetime
from playwright.sync_api import sync_playwright

# ─── CONFIGURAZIONE ─────────────────────────────────────────────────────────
PREZZO_MIN = 200
PREZZO_MAX = 380
TARGET_RAM = 16       # GB
TARGET_STORAGE = 512  # GB
TARGET_CHIP = "m1"

# Comuni e province della Campania (per il filtro ritiro)
CAMPANIA_LUOGHI = [
    "campania", "napoli", "salerno", "caserta", "avellino", "benevento",
    "nola", "pozzuoli", "ercolano", "portici", "torre del greco", "giugliano",
    "afragola", "acerra", "caivano", "frattamaggiore", "marano", "castellammare",
    "cava de' tirreni", "pagani", "nocera", "battipaglia", "eboli", "agropoli",
    "scafati", "pompei", "torre annunziata", "sorrento", "capri", "ischia",
    "aversa", "marcianise", "maddaloni", "santa maria capua vetere",
    "ariano irpino", "avella", "baiano", "solofra", "montoro",
    "airola", "montesarchio", "san giorgio del sannio", "telese"
]

# ─── EMAIL CONFIG ────────────────────────────────────────────────────────────
# Le credenziali vengono lette da variabili d'ambiente.
# In locale: imposta EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO nel tuo sistema.
# Su GitHub Actions: aggiungi questi GitHub Secrets nel repository.
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO       = os.environ.get("EMAIL_TO", EMAIL_FROM)
EMAIL_ABILITA  = bool(EMAIL_FROM and EMAIL_PASSWORD)  # True automatico se le variabili sono impostate
SMTP_SERVER    = "smtp.gmail.com"
SMTP_PORT      = 587
# ─────────────────────────────────────────────────────────────────────────────

# File per tracciare gli URL già visti (watch mode e single-run)
SEEN_URLS_FILE = Path("seen_urls.json")


@dataclass
class Offerta:
    titolo: str
    prezzo: float
    platform: str
    url: str
    ram_ok: bool
    storage_ok: bool
    manca_info: list
    location: str = ""

    def score(self) -> float:
        """Più basso il prezzo e più info verificate = punteggio migliore"""
        base = 500 - self.prezzo
        if self.ram_ok:
            base += 80
        if self.storage_ok:
            base += 80
        # Bonus mega deal: 16GB/512GB entro budget
        if self.ram_ok and self.storage_ok and self.prezzo <= 320:
            base += 300
        return base

    def stampa(self, idx: int):
        ram_label = "✅ 16GB" if self.ram_ok else "❓ RAM ?"
        sto_label = "✅ 512GB" if self.storage_ok else "❓ Storage ?"
        loc_label = f"  📍 Zona: {self.location}" if self.location else ""
        print(f"\n{'='*60}")
        print(f"  #{idx+1} [{self.platform}] {self.titolo}")
        print(f"  💶 Prezzo: {self.prezzo:.2f}€")
        print(f"  🧠 RAM: {ram_label}  |  💾 Storage: {sto_label}")
        if loc_label:
            print(loc_label)
        print(f"  🔗 {self.url}")
        if self.manca_info:
            print(f"  ⚠️  Da verificare: {', '.join(self.manca_info)}")


# ─── FUNZIONI DI FILTRO ──────────────────────────────────────────────────────

def is_wrong_chip(testo: str) -> bool:
    """
    Ritorna True se NON è M1 base.
    Esclude: M2/M3+, Intel i3/i5/i7/i9 (anche standalone), Mac mini Intel,
             model ID Intel (A1993=2018, A1347=pre-2014, 8,1=2018), anni pre-2020.
    """
    testo = testo.lower()
    # Chip Apple più nuovi
    if re.search(r'\bm[2-9]\b', testo):
        return True
    if re.search(r'm\d\s*(pro|max|ultra)', testo):
        return True
    # Intel: catch sia "i7" standalone, sia "i7-8700", sia "intel core"
    if re.search(r'\bi[3579][\s\-\d]', testo):
        return True
    if re.search(r'\bi[3579]\b', testo):
        return True
    if "intel" in testo:
        return True
    # DTK = Developer Transition Kit, chip A12Z Intel (non M1)
    if "dtk" in testo or "developer transition" in testo:
        return True
    # Model ID Intel espliciti: A1993 (2018), A1347 (2011-2014), 8,1 (2018 Intel)
    if re.search(r'\ba1993\b|\ba1347\b', testo):
        return True
    if re.search(r'\b8[,.]1\b', testo):
        return True
    # Mac mini Intel noti per anno
    if re.search(r'\b(2011|2012|2013|2014|2015|2016|2017|2018|2019)\b', testo):
        return True
    return False


def is_wrong_ram(testo: str) -> bool:
    """Ritorna True se ha esplicitamente 8GB di RAM (anche scritto '8 ram' o '8gb')"""
    testo = testo.lower()
    if '16' in testo:
        return False  # Se c'è 16 da qualche parte, non escludiamo
    # Cattura: 8gb, 8 gb, 8ram, 8 ram, /8gb, -8gb
    if re.search(r'\b8\s*(gb|ram)\b', testo):
        return True
    if re.search(r'[/\-]8\s*gb\b', testo):
        return True
    return False


def is_wrong_storage(testo: str) -> bool:
    """Ritorna True se ha esplicitamente 256GB di storage (256gb, 256g, /256, -256)"""
    testo = testo.lower()
    # Cattura: 256gb, 256 gb, 256g (opzionale 'b' finale)
    if re.search(r'\b256\s*g(b)?\b', testo) and '512' not in testo:
        return True
    if re.search(r'[/\-]256\b', testo) and '512' not in testo:
        return True
    return False


def check_ram_ok(testo: str) -> bool:
    """Conferma presenza di 16GB nel titolo"""
    return bool(re.search(r'\b16\s*gb\b', testo.lower()))


def check_storage_ok(testo: str) -> bool:
    """Conferma presenza di 512GB nel titolo"""
    return bool(re.search(r'\b512\s*gb\b', testo.lower()))


def is_broken(testo: str) -> bool:
    """Filtra prodotti rotti o non funzionanti"""
    testo = testo.lower()
    broken = [
        "rotto", "non funzionante", "pezzi di ricambio", "parts only",
        "per pezzi", "difettoso", "guasto", "schermo rotto", "no boot",
        "non si accende", "brick"
    ]
    return any(x in testo for x in broken)


def is_accessory_only(testo: str) -> bool:
    """Esclude annunci di soli accessori/cover/cavi"""
    testo = testo.lower()
    accessory_kw = ["cover", "custodia", "cavo", "alimentatore mac", "magic keyboard",
                    "magic mouse", "hub usb", "dock", "supporto"]
    return any(k in testo for k in accessory_kw) and "mac mini" not in testo


def is_pickup_only_not_campania(titolo: str, location: str) -> bool:
    """
    Ritorna True (da escludere) se l'annuncio è SOLO ritiro a mano
    E la zona NON è in Campania.
    """
    combined = (titolo + " " + location).lower()

    # Parole che indicano ritiro in persona obbligatorio
    pickup_kw = [
        "solo ritiro", "ritiro in mano", "ritiro a mano", "solo mano a mano",
        "no spedizione", "senza spedizione", "non spedisco", "non spedisco",
        "no ship", "pickup only", "ritiro personale", "consegna a mano"
    ]
    is_pickup = any(k in combined for k in pickup_kw)

    if not is_pickup:
        return False  # non è ritiro-only → OK

    # È ritiro-only: controlla se è in Campania
    in_campania = any(luogo in combined for luogo in CAMPANIA_LUOGHI)
    return not in_campania  # escludi se NON è in Campania


def info_mancanti(titolo: str) -> list:
    """Controlla info importanti assenti nel titolo"""
    testo = titolo.lower()
    mancanti = []
    if not check_ram_ok(testo):
        mancanti.append("conferma 16GB RAM")
    if not check_storage_ok(testo):
        mancanti.append("conferma 512GB storage")
    if "m1" not in testo:
        mancanti.append("conferma chip M1")
    if not any(x in testo for x in ["2020", "2021", "mneh3", "mgnr3"]):
        mancanti.append("anno/modello esatto")
    return mancanti


# ─── SCRAPER TOOLS ───────────────────────────────────────────────────────────

def human_delay(min_sec=3.0, max_sec=5.5):
    time.sleep(random.uniform(min_sec, max_sec))


def applica_filtri(titolo: str, location: str = "") -> bool:
    """Ritorna True se l'annuncio PASSA tutti i filtri (va tenuto)."""
    testo = titolo.lower()
    if "mac mini" not in testo:
        return False
    if is_wrong_chip(testo):
        return False
    if is_wrong_ram(testo):
        return False
    if is_wrong_storage(testo):
        return False
    if is_broken(testo):
        return False
    if is_accessory_only(testo):
        return False
    if is_pickup_only_not_campania(titolo, location):
        return False
    return True


# ─── VINTED ─────────────────────────────────────────────────────────────────

def cerca_vinted(context) -> List[Offerta]:
    offerte = []
    print("🔍 Cerco su Vinted...")
    page = context.new_page()
    try:
        search_url = (
            f"https://www.vinted.it/catalog"
            f"?search_text=mac%20mini%20m1"
            f"&price_from={PREZZO_MIN}&price_to={PREZZO_MAX}"
            f"&order=newest_first"
        )
        page.goto(search_url, timeout=60000)
        try:
            page.click("button#onetrust-accept-btn-handler", timeout=5000)
        except:
            pass
        page.wait_for_load_state("networkidle")
        human_delay()

        items = page.query_selector_all(".feed-grid__item")
        for item in items[:40]:
            try:
                overlay = item.query_selector("a.new-item-box__overlay")
                price_elem = item.query_selector(".web_ui__Text__subtitle")
                if not (overlay and price_elem):
                    continue

                titolo = overlay.get_attribute("title") or ""
                url_raw = overlay.get_attribute("href") or ""
                if not url_raw:
                    continue

                url = "https://www.vinted.it" + url_raw if url_raw.startswith("/") else url_raw

                prezzo_nums = re.findall(
                    r"[\d\.]+",
                    price_elem.inner_text().replace("€", "").replace(",", ".")
                )
                if not prezzo_nums:
                    continue
                prezzo = float(prezzo_nums[0])

                # Prova a leggere la location dal card
                loc_elem = item.query_selector(".web_ui__Text__caption, [class*='location']")
                location = loc_elem.inner_text() if loc_elem else ""

                if not applica_filtri(titolo, location):
                    continue

                testo = titolo.lower()
                ram_ok = check_ram_ok(testo)
                storage_ok = check_storage_ok(testo)
                manca = info_mancanti(titolo)

                offerte.append(Offerta(titolo, prezzo, "Vinted", url, ram_ok, storage_ok, manca, location))
            except:
                continue

    except Exception as e:
        print(f"  ⚠️ Errore Vinted: {e}")
    finally:
        page.close()

    print(f"  ✅ Trovate {len(offerte)} su Vinted")
    return offerte


# ─── WALLAPOP ────────────────────────────────────────────────────────────────

def cerca_wallapop(context) -> List[Offerta]:
    offerte = []
    print("🔍 Cerco su Wallapop...")
    page = context.new_page()
    try:
        search_url = (
            f"https://it.wallapop.com/app/search"
            f"?keywords=mac%20mini%20m1"
            f"&min_sale_price={PREZZO_MIN}&max_sale_price={PREZZO_MAX}"
            f"&order_by=newest"
        )
        page.goto(search_url, timeout=60000)
        try:
            page.click("#onetrust-accept-btn-handler", timeout=5000)
        except:
            pass
        page.wait_for_load_state("networkidle")
        human_delay(4, 6)
        page.evaluate("window.scrollBy(0, 800)")
        human_delay(2, 3)

        cards = page.query_selector_all("a[class*='item-card_ItemCard']")
        for card in cards[:40]:
            try:
                title_elem = card.query_selector("h3")
                price_elem = card.query_selector("strong")
                url = card.get_attribute("href") or ""
                if not (title_elem and price_elem and url):
                    continue

                titolo = title_elem.inner_text()
                prezzo_nums = re.findall(
                    r"[\d\.]+",
                    price_elem.inner_text().replace("€", "").replace(",", ".")
                )
                if not prezzo_nums:
                    continue
                prezzo = float(prezzo_nums[0])
                if not url.startswith("http"):
                    url = "https://it.wallapop.com" + url

                # Location (Wallapop mostra spesso città nel card)
                loc_elem = card.query_selector("p[class*='location'], span[class*='location'], [class*='city']")
                location = loc_elem.inner_text() if loc_elem else ""

                if not applica_filtri(titolo, location):
                    continue

                testo = titolo.lower()
                ram_ok = check_ram_ok(testo)
                storage_ok = check_storage_ok(testo)
                manca = info_mancanti(titolo)

                offerte.append(Offerta(titolo, prezzo, "Wallapop", url, ram_ok, storage_ok, manca, location))
            except:
                continue

    except Exception as e:
        print(f"  ⚠️ Errore Wallapop: {e}")
    finally:
        page.close()

    print(f"  ✅ Trovate {len(offerte)} su Wallapop")
    return offerte


# ─── SUBITO.IT ───────────────────────────────────────────────────────────────

def cerca_subito(context) -> List[Offerta]:
    offerte = []
    print("🔍 Cerco su Subito.it...")
    page = context.new_page()
    try:
        search_url = (
            f"https://www.subito.it/annunci-italia/vendita/informatica/"
            f"?q=mac+mini+m1"
            f"&ps={PREZZO_MIN}&pe={PREZZO_MAX}"
            f"&sort=datedesc"
        )
        page.goto(search_url, timeout=60000)
        try:
            page.click("button#trustarc-cookie-consent-track", timeout=5000)
        except:
            pass
        page.wait_for_load_state("domcontentloaded")
        human_delay(4, 6)

        items = page.query_selector_all(
            "a[class*='index-module_link'], div[class*='BigCard-module_card-container']"
        )
        for item in items[:40]:
            try:
                title_elem = item.query_selector("h2[class*='item-title']")
                price_elem = item.query_selector("p[class*='price']")
                link_elem = item if item.tag_name == 'a' else item.query_selector("a")
                if not (title_elem and price_elem and link_elem):
                    continue

                titolo = title_elem.inner_text()
                prezzo_raw = re.findall(
                    r"[\d\.]+",
                    price_elem.inner_text().replace("€", "").replace(".", "").replace(",", ".")
                )
                if not prezzo_raw:
                    continue
                prezzo = float(prezzo_raw[0])
                url = link_elem.get_attribute("href") or ""

                # Subito.it mostra la città nel card
                loc_elem = item.query_selector(
                    "span[class*='town'], p[class*='location'], span[class*='geo']"
                )
                location = loc_elem.inner_text() if loc_elem else ""

                if not applica_filtri(titolo, location):
                    continue

                testo = titolo.lower()
                ram_ok = check_ram_ok(testo)
                storage_ok = check_storage_ok(testo)
                manca = info_mancanti(titolo)

                offerte.append(Offerta(titolo, prezzo, "Subito", url, ram_ok, storage_ok, manca, location))
            except:
                continue

    except Exception as e:
        print(f"  ⚠️ Errore Subito: {e}")
    finally:
        page.close()

    print(f"  ✅ Trovate {len(offerte)} su Subito")
    return offerte


# ─── EBAY.IT ─────────────────────────────────────────────────────────────────

def cerca_ebay(context) -> List[Offerta]:
    offerte = []
    print("🔍 Cerco su eBay.it...")
    page = context.new_page()
    try:
        # LH_ItemCondition=3000 = usato, _sop=10 = più recenti
        search_url = (
            f"https://www.ebay.it/sch/i.html"
            f"?_nkw=mac+mini+m1+16gb"
            f"&_udlo={PREZZO_MIN}&_udhi={PREZZO_MAX}"
            f"&_sop=10"
            f"&LH_ItemCondition=3000"
        )
        page.goto(search_url, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        human_delay(3, 5)

        items = page.query_selector_all("li.s-item")
        for item in items[:40]:
            try:
                title_elem = item.query_selector("span[role='heading'], .s-item__title")
                price_elem = item.query_selector(".s-item__price")
                link_elem  = item.query_selector("a.s-item__link")
                if not (title_elem and price_elem and link_elem):
                    continue

                titolo = title_elem.inner_text().strip()
                # eBay inserisce "Nuovo annuncio" come primo result fake
                if "nuovo annuncio" in titolo.lower() or "shop on ebay" in titolo.lower():
                    continue

                url = link_elem.get_attribute("href") or ""
                # Pulisce tracking param eBay, mantiene url base
                url = url.split("?")[0] if "?" in url else url

                # Prezzo: eBay può mostrare range "200,00 € a 350,00 €"
                prezzo_raw = price_elem.inner_text().replace("€", "").replace(".", "").replace(",", ".").strip()
                prezzo_nums = re.findall(r"[\d\.]+", prezzo_raw)
                if not prezzo_nums:
                    continue
                prezzo = float(prezzo_nums[0])  # prende il prezzo minore nel range

                # Filtro prezzo doppio controllo
                if prezzo < PREZZO_MIN or prezzo > PREZZO_MAX:
                    continue

                # Location eBay
                loc_elem = item.query_selector(".s-item__location, .s-item__itemlocation")
                location = loc_elem.inner_text().replace("Da ", "").strip() if loc_elem else ""

                # Spedizione: controlla se è solo ritiro
                ship_elem = item.query_selector(".s-item__shipping, .s-item__logisticsCost")
                shipping_text = ship_elem.inner_text() if ship_elem else ""
                full_context = f"{titolo} {location} {shipping_text}"

                if not applica_filtri(titolo, full_context):
                    continue

                testo = titolo.lower()
                ram_ok = check_ram_ok(testo)
                storage_ok = check_storage_ok(testo)
                manca = info_mancanti(titolo)

                offerte.append(Offerta(titolo, prezzo, "eBay", url, ram_ok, storage_ok, manca, location))
            except:
                continue

    except Exception as e:
        print(f"  ⚠️ Errore eBay: {e}")
    finally:
        page.close()

    print(f"  ✅ Trovate {len(offerte)} su eBay")
    return offerte


# ─── MESSAGGIO CONTATTO ──────────────────────────────────────────────────────

def genera_messaggio(offerta: Offerta) -> str:
    intro = "Ciao! Sarei interessato al Mac Mini."
    domande = []
    if "conferma chip M1" in offerta.manca_info:
        domande.append("confermi che è il modello M1 (non M2 o Intel)?")
    if "conferma 16GB RAM" in offerta.manca_info:
        domande.append("ha 16GB di RAM unificata?")
    if "conferma 512GB storage" in offerta.manca_info:
        domande.append("lo storage è da 512GB SSD?")
    domande.append("funziona tutto perfettamente? Ha ancora il caricatore originale?")
    return f"{intro} {' '.join(domande).capitalize()} Grazie!"


# ─── EMAIL ───────────────────────────────────────────────────────────────────

def send_email(nuove: List[Offerta]):
    """Invia un'email con le nuove offerte trovate."""
    if not EMAIL_ABILITA or not nuove:
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🍎 {len(nuove)} nuovi Mac Mini M1 trovati! — {datetime.now().strftime('%d/%m %H:%M')}"
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO

        # Corpo testo
        testo_plain = f"Mac Mini Finder — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        testo_plain += f"Budget: {PREZZO_MIN}€ – {PREZZO_MAX}€\n\n"
        testo_plain += f"Trovate {len(nuove)} NUOVE offerte:\n\n"
        for i, o in enumerate(nuove):
            ram_str = "16GB ✅" if o.ram_ok else "RAM ?"
            sto_str = "512GB ✅" if o.storage_ok else "Storage ?"
            testo_plain += f"#{i+1} [{o.platform}] {o.titolo}\n"
            testo_plain += f"  Prezzo: {o.prezzo:.2f}€  |  {ram_str}  |  {sto_str}\n"
            testo_plain += f"  Link: {o.url}\n"
            testo_plain += f"  Messaggio: {genera_messaggio(o)}\n\n"

        # Corpo HTML
        righe_html = ""
        for i, o in enumerate(nuove):
            ram_str = "✅ 16GB" if o.ram_ok else "❓ RAM ?"
            sto_str = "✅ 512GB" if o.storage_ok else "❓ Storage ?"
            affare = "<br><b style='color:red'>🔥 AFFARE SOTTO 320€!</b>" if (o.ram_ok and o.storage_ok and o.prezzo <= 320) else ""
            loc_str = f"<br>📍 {o.location}" if o.location else ""
            msg_contatto = genera_messaggio(o)
            righe_html += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:12px;font-family:sans-serif">
              <b>#{i+1} [{o.platform}]</b> {o.titolo}<br>
              <span style="font-size:1.2em;color:#1a7a3c"><b>{o.prezzo:.2f}€</b></span>
              &nbsp;|&nbsp; {ram_str} &nbsp;|&nbsp; {sto_str}{loc_str}{affare}<br>
              <a href="{o.url}" style="color:#0066cc">👉 Vai all'annuncio</a><br>
              <small style="color:#555">📨 <i>{msg_contatto}</i></small>
            </div>"""

        html = f"""\
<html><body>
<h2 style="font-family:sans-serif">🍎 Mac Mini Finder — {datetime.now().strftime('%d/%m/%Y %H:%M')}</h2>
<p style="font-family:sans-serif">Budget: <b>{PREZZO_MIN}€ – {PREZZO_MAX}€</b> | Trovate <b>{len(nuove)}</b> nuove offerte:</p>
{righe_html}
</body></html>"""

        msg.attach(MIMEText(testo_plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

        print(f"  ✉️  Email inviata a {EMAIL_TO} con {len(nuove)} nuove offerte.")
    except Exception as e:
        print(f"  ⚠️ Errore invio email: {e}")


# ─── SEEN URLS ────────────────────────────────────────────────────────────────

def load_seen_urls() -> Set[str]:
    """Carica gli URL già notificati in precedenza."""
    if SEEN_URLS_FILE.exists():
        try:
            return set(json.loads(SEEN_URLS_FILE.read_text(encoding="utf-8")))
        except:
            pass
    return set()


def save_seen_urls(urls: Set[str]):
    """Salva gli URL visti su disco."""
    SEEN_URLS_FILE.write_text(json.dumps(list(urls), ensure_ascii=False, indent=2), encoding="utf-8")


# ─── RUN ONCE ────────────────────────────────────────────────────────────────

def run_once(seen_urls: Set[str] = None) -> List[Offerta]:
    """Esegue una singola ricerca e ritorna tutte le offerte trovate (già deduplicate)."""
    print(f"\n{'='*60}")
    print(f"  🍎 MAC MINI FINDER — Apple M1 | 16GB RAM | 512GB SSD")
    print(f"  💶 Budget: {PREZZO_MIN}€ – {PREZZO_MAX}€  (target ~300€)")
    print(f"  🚫 Filtri: Intel i3/i5/i7/i9, M2+, 8GB, 256GB, anni <2020")
    print(f"  📍 Ritiro a mano: solo se in Campania")
    print(f"  📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={'width': 1280, 'height': 800}
        )
        tutte = []
        tutte.extend(cerca_vinted(context))
        tutte.extend(cerca_wallapop(context))
        tutte.extend(cerca_subito(context))
        tutte.extend(cerca_ebay(context))
        browser.close()

    # Deduplicazione per URL
    visti = set()
    uniche = [o for o in tutte if not (o.url in visti or visti.add(o.url))]
    uniche.sort(key=lambda x: x.score(), reverse=True)

    # Offerte nuove (non ancora notificate)
    nuove = [o for o in uniche if o.url not in (seen_urls or set())]

    if not uniche:
        print("\n❌ Nessun Mac Mini M1 trovato. Prova ad allargare PREZZO_MIN/MAX.")
        return []

    # Stampa top 15
    top = uniche[:15]
    print(f"\n🏆 TOP {len(top)} OFFERTE (su {len(uniche)} totali | {len(nuove)} NUOVE):")
    for i, o in enumerate(top):
        is_new = "🆕 " if o.url in {x.url for x in nuove} else ""
        o.stampa(i)
        if o.ram_ok and o.storage_ok and o.prezzo <= 320:
            print(f"  🔥 AFFARE! Mac Mini M1 16GB/512GB sotto i 320€ — PRENDILO SUBITO!")
        print(f"  {is_new}📨 MESSAGGIO: \"{genera_messaggio(o)}\"")

    # Salva file risultati
    with open("risultati_mac_mini.txt", "w", encoding="utf-8") as f:
        f.write(f"MAC MINI FINDER — M1 16GB 512GB — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write(f"Budget: {PREZZO_MIN}€ – {PREZZO_MAX}€\n\n")
        for i, o in enumerate(uniche):
            ram_str = "16GB ✅" if o.ram_ok else "RAM ?"
            sto_str = "512GB ✅" if o.storage_ok else "Storage ?"
            loc_str = f" | 📍 {o.location}" if o.location else ""
            new_str = " [NUOVO]" if o.url in {x.url for x in nuove} else ""
            f.write(f"#{i+1}{new_str} [{o.platform}] {o.titolo} — {o.prezzo:.2f}€  [{ram_str} | {sto_str}{loc_str}]\n")
            f.write(f"  URL: {o.url}\n")
            f.write(f"  Messaggio: {genera_messaggio(o)}\n\n")

    print(f"\n✅ Risultati salvati in 'risultati_mac_mini.txt'")
    return uniche


# ─── WATCH MODE ───────────────────────────────────────────────────────────────

def watch_mode(ore: float):
    """Rilancia la ricerca ogni `ore` ore, invia email solo per le offerte nuove."""
    print(f"\n👁️  WATCH MODE — ricerca ogni {ore:.1f} ore")
    if EMAIL_ABILITA:
        print(f"  ✉️  Notifiche email → {EMAIL_TO}")
    else:
        print(f"  ⚠️  Email disabilitata — imposta EMAIL_ABILITA = True e compila le credenziali")
    print(f"  🛑  Premi Ctrl+C per fermare\n")

    seen_urls = load_seen_urls()
    iterazione = 0

    while True:
        iterazione += 1
        print(f"\n{'─'*60}")
        print(f"  🔄 Iterazione #{iterazione} — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        print(f"{'─'*60}")

        try:
            tutte = run_once(seen_urls)
        except Exception as e:
            print(f"  ⚠️ Errore durante la ricerca: {e}")
            tutte = []

        # Identifica nuove offerte
        nuove = [o for o in tutte if o.url not in seen_urls]

        if nuove:
            print(f"\n🆕 {len(nuove)} nuova/e offerta/e trovata/e!")
            for o in nuove:
                print(f"   → [{o.platform}] {o.titolo} — {o.prezzo:.2f}€  {o.url}")
            send_email(nuove)
            # Aggiorna seen_urls
            seen_urls.update(o.url for o in tutte)
            save_seen_urls(seen_urls)
        else:
            print(f"\n😴 Nessuna novità rispetto all'ultima scansione.")
            # Aggiorna comunque (nuovi annunci spariti non vengono ri-notificati)
            seen_urls.update(o.url for o in tutte)
            save_seen_urls(seen_urls)

        prossima = datetime.fromtimestamp(time.time() + ore * 3600)
        print(f"\n⏰ Prossima scansione: {prossima.strftime('%d/%m/%Y %H:%M')}")
        print(f"   (attendo {ore:.1f} ore — Ctrl+C per fermare)")
        time.sleep(ore * 3600)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Mac Mini M1 Finder — cerca offerte su Vinted, Wallapop, Subito, eBay"
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Modalità watch: rilancia la ricerca periodicamente"
    )
    parser.add_argument(
        "--hours", type=float, default=4.0,
        help="Ore tra una ricerca e l'altra in watch mode (default: 4)"
    )
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.hours)
    else:
        # Single run (usato da GitHub Actions e da CLI senza --watch)
        # Carica gli URL già visti, trova nuovi, manda email, salva
        seen_urls = load_seen_urls()
        tutte = run_once(seen_urls)
        nuove = [o for o in tutte if o.url not in seen_urls]
        if nuove:
            print(f"\n🆕 {len(nuove)} nuova/e offerta/e — invio email...")
            send_email(nuove)
        else:
            print("\n😴 Nessuna novità rispetto all'ultima scansione.")
        seen_urls.update(o.url for o in tutte)
        save_seen_urls(seen_urls)


if __name__ == "__main__":
    main()
