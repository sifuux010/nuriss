"""
Nouris Alert — Moniteur automatique et Bot Telegram interactif de billets de ferry.

Remplit le formulaire sur booking.nouriselbahrferries.com,
soumet la recherche et vous alerte (Son + Telegram) dès qu'un billet est disponible.
Répond de manière interactive à vos messages Telegram (/start, /check, /status).
"""

import json
import re
import sys
import time
import os
import ssl
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import date, datetime, timedelta

# Correction du codage de la console Windows (UTF-8)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    print("Veuillez installer Playwright:")
    print("  python -m pip install playwright")
    print("  python -m playwright install chromium")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constantes & Mappings
# ---------------------------------------------------------------------------

URL = "https://booking.nouriselbahrferries.com/en/book/journey/journeySearch/"
RESULTS_PATH = "/en/book/journey/chooseJourney/"

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "nouris_watch.json"
MIN_INTERVAL = 10

ROUTES_MAP = {
    "Alicante - Algiers":   "P~ALC-P~ALG",
    "Alicante - Oran":      "P~ALC-P~ORN",
    "Algiers - Alicante":   "P~ALG-P~ALC",
    "Algiers - Marseille":  "P~ALG-P~MAR",
    "Bejaia - Marseille":   "P~BJY-P~MAR",
    "Marseille - Algiers":   "P~MAR-P~ALG",
    "Marseille - Bejaia":   "P~MAR-P~BJY",
    "Oran - Alicante":      "P~ORN-P~ALC",
}
ROUTES = list(ROUTES_MAP.keys())

VEHICLES_MAP = {
    "Sans véhicule (Péton)": "",
    "Voiture Standard (Haut < 1.91m, Long < 6m)": "CARL",
    "Voiture Haute / SUV (Haut 1.91m-2.60m)": "CARM",
    "Grand Véhicule / Fourgon (Haut > 2.61m)": "CARH",
    "Moto": "MOTO",
    "Porte Vélo": "BIKE",
}
VEHICLES_LIST = list(VEHICLES_MAP.keys())

TRAILERS_MAP = {
    "Sans remorque": "",
    "Remorque < 4m": "TRA1",
    "Remorque 4m - 7m": "TRA2",
    "Remorque > 7m": "TRA3",
}
TRAILERS_LIST = list(TRAILERS_MAP.keys())


# ---------------------------------------------------------------------------
# Fonctions Utilitaires & Alertes
# ---------------------------------------------------------------------------

def stamp():
    """Horodatage lisible pour les journaux."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def sound_alert():
    """Joue une alerte sonore (Bip Windows ou cloche terminal)."""
    print("\n" + "!" * 64)
    print("  🎫  BILLETS DISPONIBLES — VÉRIFIEZ LE NAVIGATEUR MAINTENANT !")
    print("!" * 64)
    try:
        import winsound
        for _ in range(6):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            time.sleep(0.3)
    except Exception:
        print("\a" * 5)


DEFAULT_KEYBOARD = {
    "keyboard": [
        [
            {"text": "🔍 Vérifier Maintenant"},
            {"text": "📊 Statut & Configuration"}
        ],
        [
            {"text": "🌐 Site Officiel Nouris"},
            {"text": "❓ Aide & Commandes"}
        ]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}

def send_telegram_message(token, chat_id, text, button_url=None, custom_keyboard=None, pw_instance=None):
    """Envoie un message HTML avec boutons Telegram (Reply Keyboard ou Inline Keyboard)."""
    if not token or not chat_id:
        return False, "Token ou Chat ID non configuré."
    
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": DEFAULT_KEYBOARD
    }

    if button_url:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [
                    {
                        "text": "🎫 RÉSERVER MAINTENANT (SITE OFFICIEL)",
                        "url": button_url
                    }
                ]
            ]
        }
    elif custom_keyboard:
        payload["reply_markup"] = custom_keyboard

    if pw_instance:
        try:
            req_ctx = pw_instance.request.new_context()
            resp = req_ctx.post(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=15000)
            if resp.status == 200 and resp.json().get("ok"):
                return True, "Message envoyé via Telegram API !"
        except Exception:
            pass

    try:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        raw_data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(api_url, data=raw_data, headers=headers)
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                return True, "Message envoyé via Telegram !"
    except Exception as exc:
        return False, f"Erreur d'envoi Telegram: {exc}"

    return False, "Erreur d'envoi Telegram."


def send_telegram_alert(cfg, sailings_text, pw_instance=None):
    """Prépare et envoie l'alerte de disponibilité Telegram avec bouton d'action."""
    if not cfg.get("telegram_enabled") or not cfg.get("telegram_token") or not cfg.get("telegram_chat_id"):
        return

    veh_name = next((k for k, v in VEHICLES_MAP.items() if v == cfg.get("vehicle", "")), "Sans véhicule")
    msg = (
        "🚨 <b>NOURIS ALERT — BILLETS DISPONIBLES !</b> 🚨\n\n"
        f"🚢 <b>Trajet :</b> {cfg.get('outward_route')}\n"
        f"📅 <b>Date :</b> {cfg.get('outward_date')}\n"
        f"🚗 <b>Véhicule :</b> {veh_name}\n\n"
        "🎫 <b>Trajets Disponibles :</b>\n"
        f"<code>{sailings_text}</code>\n\n"
        "⚡ <i>Cliquez sur le bouton ci-dessous pour réserver directement !</i>"
    )
    booking_url = "https://booking.nouriselbahrferries.com/en/book/journey/journeySearch/"
    ok, status_msg = send_telegram_message(
        cfg["telegram_token"],
        cfg["telegram_chat_id"],
        msg,
        button_url=booking_url,
        pw_instance=pw_instance
    )
    if ok:
        print("  📱 Notification Telegram envoyée avec succès (avec bouton interactif) !")
    else:
        print(f"  ⚠ Impossible d'envoyer Telegram: {status_msg}")


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def verify_admin(cfg):
    """Vérifie le mot de passe Admin s'il est configuré."""
    pin = cfg.get("admin_pin", "").strip()
    if not pin:
        return True
    print("\n🔒 Zone protégée par mot de passe Admin.")
    attempt = input("  Entrez le mot de passe / PIN Admin : ").strip()
    if attempt == pin:
        print("  ✓ Accès autorisé.\n")
        return True
    print("  ❌ Mot de passe incorrect ! Accès refusé.\n")
    return False


# ---------------------------------------------------------------------------
# Gestion de la Configuration
# ---------------------------------------------------------------------------

def default_watch():
    return {
        "trip_type": "one-way",
        "outward_route": "Marseille - Algiers",
        "outward_date": "",
        "return_route": "Alicante - Algiers",
        "return_date": "",
        "vehicle": "CARL",
        "trailer": "",
        "adults": 1,
        "children": 0,
        "infants": 0,
        "interval": 20,
    }


def load_config():
    defaults = {
        "telegram_token": "",
        "telegram_chat_id": "",
        "telegram_chat_ids": [],
        "telegram_enabled": True,
        "headless": True,
        "admin_pin": "",
        "language": "fr",
        "watches": {"1": default_watch(), "2": default_watch()},
    }
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # Migration : ancien format à plat (un seul ticket) -> watches["1"]
            if "watches" not in saved and "outward_route" in saved:
                w1 = default_watch()
                for k in w1:
                    if k in saved:
                        w1[k] = saved[k]
                saved = {k: v for k, v in saved.items() if k not in w1}
                saved["watches"] = {"1": w1, "2": default_watch()}
            defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            print("Attention : Impossible de lire les paramètres sauvegardés.")

    # S'assure que les deux tickets existent toujours, même après une sauvegarde partielle.
    if not isinstance(defaults.get("watches"), dict):
        defaults["watches"] = {}
    for wid in ("1", "2"):
        if wid not in defaults["watches"]:
            defaults["watches"][wid] = default_watch()

    # Les variables d'environnement (secrets HF Spaces / VPS) prennent le dessus.
    env_token = os.environ.get("TELEGRAM_TOKEN")
    if env_token:
        defaults["telegram_token"] = env_token
    env_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if env_chat:
        defaults["telegram_chat_id"] = env_chat
    env_chats = os.environ.get("TELEGRAM_CHAT_IDS")
    if env_chats:
        defaults["telegram_chat_ids"] = [c.strip() for c in env_chats.split(",") if c.strip()]

    return defaults


def save_config(cfg):
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def ask_date(label, previous=""):
    while True:
        hint = f" [{previous}]" if previous else ""
        value = input(f"  {label} (AAAA-MM-JJ){hint}: ").strip() or previous
        try:
            chosen = date.fromisoformat(value)
            if chosen < date.today():
                print("  ⚠ La date ne peut pas être dans le passé.")
                continue
            return chosen.isoformat()
        except ValueError:
            print("  ⚠ Utilisez le format AAAA-MM-JJ, ex: 2026-10-16")


def ask_number(label, previous, lo, hi):
    while True:
        raw = input(f"  {label} [{previous}]: ").strip()
        if not raw:
            return previous
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print(f"  ⚠ Entrez un nombre entre {lo} et {hi}.")


def choose_option(title, options_list, current_val_code, mapping):
    print(f"\n  {title} :")
    current_label = next((k for k, v in mapping.items() if v == current_val_code), options_list[0])
    for i, opt in enumerate(options_list, 1):
        marker = " ← (actuel)" if opt == current_label else ""
        print(f"    {i}. {opt}{marker}")
    while True:
        raw = input(f"  Faites votre choix [Actuel: {current_label}]: ").strip()
        if not raw:
            return mapping[current_label]
        if raw.isdigit() and 1 <= int(raw) <= len(options_list):
            selected_name = options_list[int(raw) - 1]
            return mapping[selected_name]
        print("  ⚠ Numéro invalide.")


def configure(cfg):
    if not verify_admin(cfg):
        return

    print("\n╔══════════════════════════════════════════╗")
    print("║      CONFIGURER TRAJET, DATE ET VOITURE  ║")
    print("╚══════════════════════════════════════════╝")

    mode = input("\n  Type de voyage — 1 = Aller simple, 2 = Aller-Retour [1]: ").strip()
    cfg["trip_type"] = "return" if mode == "2" else "one-way"

    cfg["outward_route"] = choose_option("Trajet aller", ROUTES, cfg.get("outward_route", "Marseille - Algiers"), ROUTES_MAP)
    cfg["outward_date"] = ask_date("Date aller", cfg.get("outward_date", "2026-10-16"))

    if cfg["trip_type"] == "return":
        cfg["return_route"] = choose_option("Trajet retour", ROUTES, cfg.get("return_route", "Alicante - Algiers"), ROUTES_MAP)
        while True:
            cfg["return_date"] = ask_date("Date retour", cfg.get("return_date", ""))
            if cfg["return_date"] >= cfg["outward_date"]:
                break
            print("  ⚠ La date retour doit être égale ou postérieure à la date aller.")

    cfg["vehicle"] = choose_option("Option Véhicule / Voiture", VEHICLES_LIST, cfg.get("vehicle", "CARL"), VEHICLES_MAP)
    cfg["trailer"] = choose_option("Option Remorque / Extra", TRAILERS_LIST, cfg.get("trailer", ""), TRAILERS_MAP)

    cfg["interval"] = ask_number(
        "Intervalle de vérification en secondes (ex: 60 pour 1 min)",
        max(MIN_INTERVAL, int(cfg.get("interval", 60))),
        MIN_INTERVAL, 86400,
    )

    save_config(cfg)
    print("\n  ✓ Configuration enregistrée avec succès.\n")


def configure_passengers(cfg):
    if not verify_admin(cfg):
        return

    print("\n╔══════════════════════════════════════════╗")
    print("║      MODIFIER LE NOMBRE DE PASSAGERS     ║")
    print("╚══════════════════════════════════════════╝")

    cfg["adults"] = ask_number("Adultes (1–20)", int(cfg.get("adults", 1)), 1, 20)
    cfg["children"] = ask_number("Enfants 3–12 (0–20)", int(cfg.get("children", 0)), 0, 20)
    cfg["infants"] = ask_number("Bébés 0–3 (0–20)", int(cfg.get("infants", 0)), 0, 20)

    save_config(cfg)
    print("\n  ✓ Passagers mis à jour.")


def configure_telegram(cfg):
    if not verify_admin(cfg):
        return

    print("\n╔══════════════════════════════════════════╗")
    print("║        CONFIGURATION TELEGRAM BOT        ║")
    print("╚══════════════════════════════════════════╝")

    cur_tok = cfg.get("telegram_token", "")
    cur_chat = cfg.get("telegram_chat_id", "")
    cur_en = cfg.get("telegram_enabled", True)

    print(f"\n  Statut actuel Telegram : {'Activé' if cur_en else 'Désactivé'}")
    tok = input(f"  Bot Token Telegram [{cur_tok[:10]}...]: ").strip() or cur_tok
    chat = input(f"  Chat ID Telegram [{cur_chat}]: ").strip() or cur_chat

    en_choice = input("  Activer les alertes Telegram ? (o/n) [o]: ").strip().lower()
    enabled = True if en_choice != "n" else False

    cfg["telegram_token"] = tok
    cfg["telegram_chat_id"] = chat
    cfg["telegram_enabled"] = enabled

    save_config(cfg)
    print("\n  ✓ Configuration Telegram enregistrée.")

    if tok and chat:
        test_now = input("\n  Envoyer un message de test sur Telegram maintenant ? (o/n) [o]: ").strip().lower()
        if test_now != "n":
            ok, msg = send_telegram_message(
                tok, chat,
                "🚢 <b>NOURIS ALERT</b> — Test de connexion Telegram réussi ! Le bot est configuré."
            )
            if ok:
                print("  ✓ Message de test envoyé avec succès sur Telegram !")
            else:
                print(f"  ❌ Erreur: {msg}")


def configure_admin(cfg):
    print("\n╔══════════════════════════════════════════╗")
    print("║       GESTION ACCÈS ET MOT DE PASSE      ║")
    print("╚══════════════════════════════════════════╝")

    if not verify_admin(cfg):
        return

    cur_pin = cfg.get("admin_pin", "")
    if cur_pin:
        print("  Un mot de passe Admin est actuellement configuré.")
        opt = input("  1 = Modifier le mot de passe, 2 = Supprimer la protection [1]: ").strip()
        if opt == "2":
            cfg["admin_pin"] = ""
            save_config(cfg)
            print("  ✓ Protection Admin désactivée.")
            return

    new_pin = input("  Entrez le nouveau mot de passe / PIN Admin (ou vide pour désactiver) : ").strip()
    cfg["admin_pin"] = new_pin
    save_config(cfg)
    if new_pin:
        print("  ✓ Mot de passe Admin configuré avec succès.")
    else:
        print("  ✓ Mot de passe Admin désactivé.")


def show_config(cfg):
    veh_label = next((k for k, v in VEHICLES_MAP.items() if v == cfg.get("vehicle", "")), "Sans véhicule")
    tr_label = next((k for k, v in TRAILERS_MAP.items() if v == cfg.get("trailer", "")), "Sans remorque")

    print("\n┌────────────────────────────────────────────────────────┐")
    print("│              CONFIGURATION ACTUELLE                   │")
    print("├────────────────────────────────────────────────────────┤")
    print(f"│  Type de voyage : {cfg.get('trip_type', 'one-way'):<34} │")
    print(f"│  Trajet aller   : {cfg.get('outward_route', 'N/A'):<34} │")
    print(f"│  Date aller     : {cfg.get('outward_date', 'N/A'):<34} │")
    if cfg.get("trip_type") == "return":
        print(f"│  Trajet retour  : {cfg.get('return_route', 'N/A'):<34} │")
        print(f"│  Date retour    : {cfg.get('return_date', 'N/A'):<34} │")
    print(f"│  Véhicule       : {veh_label[:34]:<34} │")
    print(f"│  Remorque       : {tr_label[:34]:<34} │")
    print(f"│  Passagers      : {cfg.get('adults', 1)} Adulte(s), {cfg.get('children', 0)} Enfant(s)            │")
    print(f"│  Intervalle     : {cfg.get('interval')} secondes ({cfg.get('interval')//60} min {cfg.get('interval')%60}s)           │")
    tg_stat = "Activé" if cfg.get("telegram_enabled") and cfg.get("telegram_token") else "Désactivé"
    print(f"│  Telegram       : {tg_stat:<34} │")
    adm_stat = "Protégé" if cfg.get("admin_pin") else "Non protégé"
    print(f"│  Accès Admin    : {adm_stat:<34} │")
    print("└────────────────────────────────────────────────────────┘")


# ---------------------------------------------------------------------------
# Interaction Formulaire & Playwright
# ---------------------------------------------------------------------------

def fill_and_submit(page, cfg):
    """Remplissage dynamique du formulaire par JavaScript."""
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # 1. Fermeture pop-up / cookies si présents
    page.evaluate("""() => {
        const btn = document.querySelector('.cw-cookie-accept, #accept-cookies, .cookie-btn');
        if (btn) btn.click();
    }""")

    # 2. Type de voyage
    flow_val = "RETURN" if cfg["trip_type"] == "return" else "ONEWAY"
    page.evaluate("""(flow) => {
        const rad = document.querySelector('input[name="bookingflow"][value="' + flow + '"]');
        if (rad) {
            rad.checked = true;
            rad.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }""", flow_val)
    page.wait_for_timeout(500)

    # 3. Numéro de voyages
    num_jrys = "2" if cfg["trip_type"] == "return" else "1"
    page.evaluate("""(n) => {
        const h = document.querySelector('input[name="cw_journeysearch_numJrys"]');
        if (h) h.value = n;
    }""", num_jrys)

    # 4. Trajet Aller
    route_val = ROUTES_MAP.get(cfg["outward_route"], "")
    if not route_val:
        raise RuntimeError(f"Trajet inconnu : {cfg['outward_route']}")

    page.evaluate("""(routeVal) => {
        const sel = document.querySelector('select[name="cw_journeysearch_j1_route"]');
        if (!sel) throw new Error('Menu déroulant trajet introuvable');
        sel.value = routeVal;
        sel.dispatchEvent(new Event('change', {bubbles: true}));
        if (typeof jQuery !== 'undefined') jQuery(sel).trigger('change');
    }""", route_val)
    page.wait_for_timeout(800)

    # 5. Date Aller
    _set_date_via_calendar(page, 1, cfg["outward_date"])

    # 6. Véhicule Aller
    _set_vehicle_and_extras(page, 1, cfg)

    # 7. Passagers Aller
    _set_passengers(page, 1, cfg)

    # 8. Si retour
    if cfg["trip_type"] == "return":
        ret_route_val = ROUTES_MAP.get(cfg["return_route"], "")
        if ret_route_val:
            page.evaluate("""(routeVal) => {
                const sel = document.querySelector('select[name="cw_journeysearch_j2_route"]');
                if (sel) {
                    sel.value = routeVal;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    if (typeof jQuery !== 'undefined') jQuery(sel).trigger('change');
                }
            }""", ret_route_val)
            page.wait_for_timeout(800)

        _set_date_via_calendar(page, 2, cfg["return_date"])
        _set_vehicle_and_extras(page, 2, cfg)
        _set_passengers(page, 2, cfg)

    # 9. Soumission du formulaire
    page.evaluate("""() => {
        const btn = document.querySelector('button.cw-action-next[type="submit"]');
        if (!btn) throw new Error('Bouton de soumission introuvable');
        btn.click();
    }""")

    # 10. Attente de la page des résultats
    try:
        page.wait_for_url("**/chooseJourney/**", timeout=30000)
    except PlaywrightTimeoutError:
        pass

    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(3000)

    body_text = page.locator("body").inner_text(timeout=10000)
    return body_text, page.url


def _set_date_via_calendar(page, journey_num, target_date):
    if not target_date:
        raise RuntimeError(f"Aucune date configurée pour le voyage {journey_num}")

    year_month = target_date[:7]
    day = int(target_date[8:10])
    journey_selector = f".cw-journeysearch-journey-{journey_num}"

    page.evaluate("""(args) => {
        const {journeySelector, yearMonth} = args;
        const container = document.querySelector(journeySelector);
        if (!container) return;
        const monthSelect = container.querySelector('select.cw-change-month');
        if (monthSelect) {
            monthSelect.value = yearMonth;
            monthSelect.dispatchEvent(new Event('change', {bubbles: true}));
            if (typeof jQuery !== 'undefined') jQuery(monthSelect).trigger('change');
        }
    }""", {"journeySelector": journey_selector, "yearMonth": year_month})
    page.wait_for_timeout(1000)

    page.evaluate("""(args) => {
        const {journeySelector, day, targetDate} = args;
        const container = document.querySelector(journeySelector);
        if (!container) return;
        const dayCells = container.querySelectorAll('.cw-calendar-day, .cw-cal-day, td[data-date], td.day, .day');
        for (const cell of dayCells) {
            const dateAttr = cell.getAttribute('data-date') || cell.getAttribute('data-cw-date') || '';
            const cellText = (cell.textContent || '').trim();
            const dayNum = parseInt(cellText, 10);
            if (dateAttr === targetDate || dayNum === day) {
                cell.click();
                return;
            }
        }
    }""", {"journeySelector": journey_selector, "day": day, "targetDate": target_date})
    page.wait_for_timeout(400)

    page.evaluate("""(args) => {
        const {journeyNum, targetDate} = args;
        const dateInput = document.querySelector('input[name="cw_journeysearch_j' + journeyNum + '_date"]');
        if (dateInput) {
            dateInput.classList.remove('date-sold-out');
            dateInput.value = targetDate;
            dateInput.dispatchEvent(new Event('change', {bubbles: true}));
            if (typeof jQuery !== 'undefined') jQuery(dateInput).trigger('change');
        }
    }""", {"journeyNum": journey_num, "targetDate": target_date})
    page.wait_for_timeout(300)


def _set_vehicle_and_extras(page, journey_num, cfg):
    veh_val = cfg.get("vehicle", "")
    extra_val = cfg.get("trailer", "")

    page.evaluate("""(args) => {
        const {jn, vehVal, extraVal} = args;

        const vehSel = document.querySelector('select[name="cw_journeysearch_j' + jn + '_vehicles[0][ctg]"]');
        if (vehSel) {
            vehSel.value = vehVal;
            vehSel.dispatchEvent(new Event('change', {bubbles: true}));
            if (typeof jQuery !== 'undefined') jQuery(vehSel).trigger('change');
        }
        const vehQty = document.querySelector('select[name="cw_journeysearch_j' + jn + '_vehicles[0][qty]"]');
        if (vehQty) {
            vehQty.value = vehVal ? '1' : '';
            vehQty.dispatchEvent(new Event('change', {bubbles: true}));
        }

        const extraSel = document.querySelector('select[name="cw_journeysearch_j' + jn + '_extras[0][ctg]"]');
        if (extraSel) {
            extraSel.value = extraVal;
            extraSel.dispatchEvent(new Event('change', {bubbles: true}));
            if (typeof jQuery !== 'undefined') jQuery(extraSel).trigger('change');
        }
        const extraQty = document.querySelector('select[name="cw_journeysearch_j' + jn + '_extras[0][qty]"]');
        if (extraQty) {
            extraQty.value = extraVal ? '1' : '';
            extraQty.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }""", {"jn": journey_num, "vehVal": veh_val, "extraVal": extra_val})


def _set_passengers(page, journey_num, cfg):
    mappings = [
        (1, str(cfg.get("adults", 1))),
        (2, str(cfg.get("children", 0))),
        (3, str(cfg.get("infants", 0)))
    ]
    for cat_idx, qty in mappings:
        page.evaluate("""(args) => {
            const {jn, catIdx, qty} = args;
            const sel = document.querySelector('select[name="cw_journeysearch_j' + jn + '_passengers[' + catIdx + '][qty]"]');
            if (sel) {
                sel.value = qty;
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""", {"jn": journey_num, "catIdx": cat_idx, "qty": qty})


# ---------------------------------------------------------------------------
# Classification & Analyse des Résultats
# ---------------------------------------------------------------------------

def _date_to_ddmmyyyy(iso_date):
    """Convertit 'AAAA-MM-JJ' en 'JJ-MM-AAAA' (format utilisé sur le site)."""
    try:
        y, m, d = iso_date.split("-")
        return f"{d}-{m}-{y}"
    except Exception:
        return ""


def classify_result(text, url, target_date=None):
    low = text.casefold()
    is_results_page = "choosejourney" in url.casefold()

    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    target_ddmmyyyy = _date_to_ddmmyyyy(target_date) if target_date else None

    avail_sailings = []
    unavail_sailings = []

    for i, line in enumerate(lines):
        if re.search(r'\d{2}-\d{2}-\d{4}', line) and re.search(r'\d{1,2}:\d{2}', line):
            # Ignore les traversées d'une autre date (le site affiche les dates voisines)
            if target_ddmmyyyy and target_ddmmyyyy not in line:
                continue
            # Regroupe la ligne et les 3 suivantes (prix / "unavailable" peuvent être sur ligne séparée)
            block = " ".join(lines[i:i+4]).casefold()
            is_unavail = ("unavailable" in block or "sold out" in block
                          or "complet" in block or "disabled" in block)
            has_price = bool(re.search(r'\d+[\.,]\d{2}\s*€', block) or '€' in block)

            if has_price and not is_unavail:
                avail_sailings.append(line)
            else:
                unavail_sailings.append(line)

    if avail_sailings:
        return "AVAILABLE"

    if unavail_sailings or "departure unavailable" in low or "sold out" in low:
        return "UNAVAILABLE"

    unavailable_phrases = [
        "no journeys available", "no journey available", "no availability",
        "no results found", "no sailings available", "there are no journeys",
        "not available for the selected", "no departures", "no trips available"
    ]
    if any(phrase in low for phrase in unavailable_phrases):
        return "UNAVAILABLE"

    if is_results_page:
        return "UNAVAILABLE"

    return "UNKNOWN"


def extract_sailings(text, only_available=True, target_date=None):
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    target_ddmmyyyy = _date_to_ddmmyyyy(target_date) if target_date else None
    sailings = []
    for i, line in enumerate(lines):
        if re.search(r'\d{2}-\d{2}-\d{4}', line) and re.search(r'\d{1,2}:\d{2}', line):
            if target_ddmmyyyy and target_ddmmyyyy not in line:
                continue
            # Regarde la ligne et les 3 suivantes pour trouver prix / unavailable
            block_lines = lines[i:i+4]
            block = " ".join(block_lines).casefold()
            is_unavail = "unavailable" in block or "sold out" in block or "complet" in block
            price_match = re.search(r'(\d+[\.,]\d{2}\s*€)', " ".join(block_lines))
            price_str = price_match.group(1) if price_match else ""
            has_price = bool(price_str)
            full = line if not price_str else f"{line}  —  {price_str}"

            if only_available:
                if has_price and not is_unavail:
                    sailings.append(full)
            else:
                sailings.append(full)
    return sailings


# ---------------------------------------------------------------------------
# Ecouteur des Commandes Telegram (Single Thread / Main Context)
# ---------------------------------------------------------------------------

def check_telegram_commands(pw, token, chat_id_target, offset, cfg):
    """Vérifie les commandes envoyées sur Telegram et y répond directement."""
    if not token or not chat_id_target or not cfg.get("telegram_enabled"):
        return offset, None

    req_ctx = pw.request.new_context()
    try:
        resp = req_ctx.post(f"https://api.telegram.org/bot{token}/getUpdates", data={"offset": offset, "timeout": 0}, timeout=5000)
        if resp.status == 200:
            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                raw_text = (msg.get("text") or "").strip()
                sender_id = str(msg.get("from", {}).get("id", ""))

                if sender_id != chat_id_target or not raw_text:
                    continue

                low_text = raw_text.casefold()
                cmd = raw_text.split()[0].lower()
                veh_name = next((k for k, v in VEHICLES_MAP.items() if v == cfg.get("vehicle", "")), "Sans véhicule")
                booking_url = "https://booking.nouriselbahrferries.com/en/book/journey/journeySearch/"

                if cmd in ["/start", "/status", "/help"] or "statut" in low_text or "aide" in low_text or "configuration" in low_text:
                    reply = (
                        "🚢 <b>NOURIS ALERT — BOT TELEGRAM INTERACTIF PRÊT !</b> 🚢\n\n"
                        "👋 Bonjour <b>sifuux_10</b> ! Vos boutons de commande sont activés au bas de l'écran.\n\n"
                        f"🟢 <b>Surveillance :</b> Active en arrière-plan\n"
                        f"📌 <b>Trajet :</b> {cfg.get('outward_route')}\n"
                        f"📅 <b>Date :</b> {cfg.get('outward_date')}\n"
                        f"🚗 <b>Véhicule :</b> {veh_name}\n"
                        f"⏱️ <b>Intervalle :</b> {cfg.get('interval')}s ({cfg.get('interval')//60} min)\n\n"
                        "<b>💬 Cliquez simplement sur les boutons au bas de votre écran Telegram :</b>\n"
                        "🔹 <b>🔍 Vérifier Maintenant</b> — Recherche immédiate sur le site\n"
                        "🔹 <b>📊 Statut & Configuration</b> — Informations actuelles\n"
                        "🔹 <b>🌐 Site Officiel Nouris</b> — Ouvrir la réservation\n\n"
                        "<i>Dès qu'une place se libère, une alerte sonore et prioritaire s'affiche ici !</i>"
                    )
                    send_telegram_message(token, chat_id_target, reply, pw_instance=pw)
                    print(f"\n  📱 Réponse Telegram envoyée à sifuux_10 pour: '{raw_text}' !")

                elif "site officiel" in low_text:
                    reply = (
                        "🌐 <b>ACCÈS DIRECT AU SITE OFFICIEL NOURIS ELBAHR FERRIES</b>\n\n"
                        "Cliquez sur le bouton ci-dessous pour accéder au formulaire de réservation :"
                    )
                    send_telegram_message(token, chat_id_target, reply, button_url=booking_url, pw_instance=pw)

                elif cmd in ["/check", "/search", "/test"] or "vérifier" in low_text or "verifier" in low_text or "check" in low_text:
                    send_telegram_message(
                        token, chat_id_target,
                        "🔍 <b>Vérification immédiate en cours sur Nouris Ferries...</b> Veuillez patienter quelques secondes.",
                        pw_instance=pw
                    )
                    print(f"\n  📱 Demande de vérification reçue depuis Telegram ('{raw_text}') ! Lancement immédiat...")
                    return offset, "check"

    except Exception:
        pass

    return offset, None


# ---------------------------------------------------------------------------
# Boucle de Surveillance Automatique
# ---------------------------------------------------------------------------

def monitor(cfg):
    """Boucle principale de surveillance répétée avec bot Telegram interactif."""
    show_config(cfg)
    print(f"\n[{stamp()}] 🚀 Démarrage du Bot Telegram et de la surveillance...")
    print("Le bot écoute en direct vos messages Telegram (/start, /check, /status).")
    print("Appuyez sur Ctrl+C pour arrêter à tout moment.\n")

    is_headless = cfg.get("headless", True)
    token = cfg.get("telegram_token")
    chat_id_target = str(cfg.get("telegram_chat_id", ""))
    booking_url = "https://booking.nouriselbahrferries.com/en/book/journey/journeySearch/"

    with sync_playwright() as pw:
        # Message initial de confirmation sur Telegram
        if token and chat_id_target:
            send_telegram_message(
                token, chat_id_target,
                "🚢 <b>NOURIS ALERT — BOT INTERACTIF ACTIVÉ !</b> 🚢\n\n"
                "✅ Le bot est démarré et écoute vos commandes.\n"
                "Tapez <b>/check</b> pour lancer une vérification immédiate ou <b>/status</b> pour voir les détails !",
                button_url=booking_url,
                pw_instance=pw
            )
            print("  📱 Message de connexion envoyé sur votre Telegram (Chat ID: 5709294728) !")

        browser = pw.chromium.launch(headless=is_headless)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(30000)

        check_num = 0
        offset = 0
        last_search_time = 0
        prev_status = None

        try:
            while True:
                now = time.time()
                interval = max(MIN_INTERVAL, int(cfg.get("interval", 60)))

                # 1. Écoute des commandes Telegram en temps réel
                offset, cmd = check_telegram_commands(pw, token, chat_id_target, offset, cfg)

                # 2. Si /check demandé sur Telegram OU si l'intervalle de temps est écoulé
                if cmd == "check" or (now - last_search_time >= interval):
                    last_search_time = time.time()
                    check_num += 1
                    is_manual = (cmd == "check")
                    lbl = "sur demande Telegram (/check)" if is_manual else f"#{check_num}"

                    print(f"\n{'─' * 55}")
                    print(f"[{stamp()}] Vérification {lbl}")

                    try:
                        text, result_url = fill_and_submit(page, cfg)
                        status = classify_result(text, result_url, target_date=cfg.get("outward_date"))

                        print(f"  URL Résultat : {result_url}")
                        print(f"  Statut       : {status}")

                        if status == "AVAILABLE":
                            sailings = extract_sailings(text, only_available=True, target_date=cfg.get("outward_date"))
                            sailings_str = "\n".join([f"• {s}" for s in sailings])

                            print("\n" + "!" * 64)
                            print(f"  🚨 BILLETS LIBÉRÉS ! {len(sailings)} TRAVERSÉE(S) DISPONIBLE(S) !")
                            print("!" * 64)
                            for s in sailings:
                                print(f"    → {s}")

                            sound_alert()
                            send_telegram_alert(cfg, sailings_str, pw_instance=pw)
                            prev_status = "AVAILABLE"

                        elif status == "UNAVAILABLE":
                            print("  ✗ Aucun billet disponible actuellement.")
                            all_found = extract_sailings(text, only_available=False, target_date=cfg.get("outward_date"))
                            if all_found:
                                print("  Traversée répertoriée sur cette date, mais non réservable :")
                                for s in all_found:
                                    print(f"    → {s}")

                            if is_manual:
                                tg_rep = (
                                    f"✗ <b>Aucun billet disponible actuellement</b> pour le trajet {cfg.get('outward_route')} le {cfg.get('outward_date')}.\n\n"
                                    f"<i>Le bot continue de surveiller en arrière-plan toutes les {cfg.get('interval')}s !</i>"
                                )
                                send_telegram_message(token, chat_id_target, tg_rep, pw_instance=pw)

                            prev_status = "UNAVAILABLE"

                        else:
                            print("  ? Statut incertain ou erreur d'affichage de la page.")
                            snippet = re.sub(r'\s+', ' ', text)[:500]
                            print(f"  Extrait page : {snippet}")
                            prev_status = "UNKNOWN"

                    except Exception as exc:
                        print(f"  ✗ Erreur de recherche : {type(exc).__name__}: {exc}")

                time.sleep(1)

        except KeyboardInterrupt:
            print(f"\n[{stamp()}] 🛑 Surveillance arrêtée par l'utilisateur.")
        finally:
            try:
                browser.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Test Unique
# ---------------------------------------------------------------------------

def test_search(cfg):
    show_config(cfg)
    print(f"\n[{stamp()}] 🧪 Exécution d'un test de recherche...")

    is_headless = cfg.get("headless", True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=is_headless)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(30000)

        try:
            text, result_url = fill_and_submit(page, cfg)
            status = classify_result(text, result_url, target_date=cfg.get("outward_date"))

            print(f"\n  URL Résultat : {result_url}")
            print(f"  Statut       : {status}")

            if status == "AVAILABLE":
                sailings = extract_sailings(text, only_available=True, target_date=cfg.get("outward_date"))
                sailings_str = "\n".join([f"• {s}" for s in sailings])
                print("\n" + "!" * 60)
                print(f"  🎫 BILLETS DISPONIBLES — {len(sailings)} TRAVERSÉE(S) TROUVÉE(S) !")
                print("  " + "!" * 60)
                for s in sailings:
                    print(f"    → {s}")
                sound_alert()
                send_telegram_alert(cfg, sailings_str, pw_instance=pw)
            elif status == "UNAVAILABLE":
                print("  ✗ Aucun billet disponible pour cette recherche.")
                all_found = extract_sailings(text, only_available=False, target_date=cfg.get("outward_date"))
                if all_found:
                    print("  Traversée répertoriée sur la date, mais marquée non disponible :")
                    for s in all_found:
                        print(f"    → {s}")
            else:
                print("  ? Résultat peu clair. Texte extrait de la page :")
                print(re.sub(r'\s+', ' ', text)[:1500])

            input("\n  Appuyez sur Entrée pour fermer le navigateur et revenir au menu...")

        except Exception as exc:
            print(f"\n  ✗ Erreur lors du test : {type(exc).__name__}: {exc}")
            input("  Appuyez sur Entrée pour revenir au menu...")
        finally:
            try:
                browser.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Menu Principal
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()

    args = [a.lower().strip() for a in sys.argv[1:]]
    if any(arg in args for arg in ["--auto", "-a", "auto", "start", "monitor", "--monitor", "--start"]):
        if not cfg.get("outward_date"):
            print("⚠ Veuillez d'abord configurer la date et le trajet.")
            sys.exit(1)
        print(f"[{stamp()}] 🚀 Démarrage direct de la surveillance...")
        monitor(cfg)
        return

    while True:
        clear()
        print()
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║               🚢  NOURIS ALERT — FERRIES  🚢                 ║")
        print("║       Système de Surveillance Automatique de Billets        ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print()
        print("  1. ⚙️  Configurer Trajet, Date & Voiture")
        print("  2. 📊  Afficher la configuration actuelle")
        print("  3. 👥  Ajuster les passagers (Optionnel)")
        print("  4. 📱  Configurer Telegram (Bot Token & Chat ID)")
        print("  5. 🔒  Sécurité / Mot de passe Admin")
        print("  6. 🧪  Tester une recherche (1 essai)")
        print("  7. 🚀  Démarrer la surveillance automatique")
        print("  8. 🚪  Quitter")
        print()

        choice = input("  Faites votre choix [1-8] : ").strip()

        if choice == "1":
            try:
                configure(cfg)
            except (KeyboardInterrupt, EOFError):
                print("\n  Configuration annulée.")
            input("  Appuyez sur Entrée pour continuer...")

        elif choice == "2":
            show_config(cfg)
            input("\n  Appuyez sur Entrée pour continuer...")

        elif choice == "3":
            try:
                configure_passengers(cfg)
            except (KeyboardInterrupt, EOFError):
                print("\n  Configuration passagers annulée.")
            input("  Appuyez sur Entrée pour continuer...")

        elif choice == "4":
            try:
                configure_telegram(cfg)
            except (KeyboardInterrupt, EOFError):
                print("\n  Configuration Telegram annulée.")
            input("  Appuyez sur Entrée pour continuer...")

        elif choice == "5":
            try:
                configure_admin(cfg)
            except (KeyboardInterrupt, EOFError):
                print("\n  Configuration Admin annulée.")
            input("  Appuyez sur Entrée pour continuer...")

        elif choice == "6":
            if not cfg.get("outward_date"):
                print("\n  ⚠ Veuillez d'abord configurer le trajet et la date (Option 1).")
                input("  Appuyez sur Entrée pour continuer...")
                continue
            test_search(cfg)

        elif choice == "7":
            if not cfg.get("outward_date"):
                print("\n  ⚠ Veuillez d'abord configurer le trajet et la date (Option 1).")
                input("  Appuyez sur Entrée pour continuer...")
                continue
            monitor(cfg)
            input("\n  Appuyez sur Entrée pour continuer...")

        elif choice == "8":
            print("\n  Au revoir !")
            break

        else:
            print("  Veuillez choisir un chiffre entre 1 et 8.")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nArrêté par l'utilisateur.")
        sys.exit(0)