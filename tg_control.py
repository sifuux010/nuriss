"""
Nouris Alert — Bot Telegram piloté entièrement depuis Telegram.
Surveille jusqu'à 2 tickets en parallèle (indépendants), FR/AR,
démarrage/arrêt par ticket, historique combiné, configuration par ticket.
"""
import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.parse
import html
import threading
from pathlib import Path
from datetime import datetime

import requests
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.sync_api import sync_playwright

from nouris_bot import (
    load_config, save_config, fill_and_submit,
    classify_result, extract_sailings,
    ROUTES_MAP, VEHICLES_MAP, stamp, DATA_DIR,
)

BASE = Path(__file__).resolve().parent
HIST_FILE = DATA_DIR / "history.jsonl"
BOOKING_URL = "https://booking.nouriselbahrferries.com/en/book/journey/journeySearch/"
WATCH_IDS = ("1", "2")

# ---------------------------------------------------------------------------
# Traductions FR / AR
# ---------------------------------------------------------------------------
T = {
    "fr": {
        "welcome": "🚢 <b>NOURIS ALERT</b>\n\nBot de surveillance de billets ferry.\nChoisissez un ticket à gérer, ou consultez l'historique.",
        "menu": "📋 Menu principal",
        "start": "▶️ Démarrer",
        "stop": "⏹️ Arrêter",
        "status": "📊 Statut",
        "history": "📜 Historique",
        "config": "⚙️ Configurer",
        "language": "🌐 Langue",
        "started": "✅ Ticket {n} : surveillance <b>DÉMARRÉE</b>. Vérification toutes les {interval}s sans arrêt jusqu'à trouver un billet.",
        "stopped": "⏹️ Ticket {n} : surveillance <b>ARRÊTÉE</b>.",
        "already_running": "⚠️ Déjà en cours.",
        "already_stopped": "⚠️ Déjà arrêté.",
        "ticket_num": "Ticket {n}",
        "start_header": "▶️ Quel ticket voulez-vous démarrer ?",
        "stop_header": "⏹️ Quel ticket voulez-vous arrêter ?",
        "config_header": "⚙️ Quel ticket voulez-vous configurer ?",
        "start_all": "▶️ Démarrer les 2 tickets",
        "stop_all": "⏹️ Arrêter les 2 tickets",
        "started_multi": "✅ Surveillance démarrée pour : {list}.",
        "stopped_multi": "⏹️ Surveillance arrêtée pour : {list}.",
        "skipped_note": "⚠️ Ticket {n} ignoré (trajet/date non configurés).",
        "status_title": "📊 <b>STATUT — TOUS LES TICKETS</b>",
        "watch_body": (
            "🎫 <b>TICKET {n}</b>\n\n"
            "État : {state}\n"
            "Trajet : {route}\n"
            "Date : {date}\n"
            "Véhicule : {vehicle}\n"
            "Intervalle : {interval}s\n"
            "Vérifications : <b>{count}</b>\n"
            "Dernière vérification : {last}\n"
            "Dernier résultat : {last_result}"
        ),
        "state_running": "🟢 EN MARCHE",
        "state_stopped": "🔴 ARRÊTÉ",
        "state_paused": "🟡 EN PAUSE (billet trouvé)",
        "never": "jamais",
        "history_title": "📜 <b>HISTORIQUE</b> (20 dernières vérifications, tous tickets)",
        "history_empty": "Aucune vérification encore enregistrée.",
        "ticket_found": (
            "🚨 <b>BILLET DISPONIBLE — TICKET {n} !</b> 🚨\n\n"
            "🚢 Trajet : {route}\n"
            "📅 Date : {date}\n\n"
            "🎫 <b>Traversées :</b>\n<code>{sailings}</code>\n\n"
            "⚡ <i>Réservez vite avant les autres !</i>"
        ),
        "book_now": "🎫 RÉSERVER MAINTENANT",
        "continue_search": "▶️ Continuer la recherche",
        "stop_bot": "⏹️ Arrêter",
        "back_menu": "📋 Menu",
        "config_body": (
            "⚙️ <b>CONFIGURATION — TICKET {n}</b>\n\n"
            "Type : <b>{triptype}</b>\n"
            "Aller : <b>{route}</b> — <b>{date}</b>\n"
            "{return_line}"
            "Véhicule : <b>{vehicle}</b>\n"
            "Passagers : <b>{adults}A / {children}E / {infants}B</b>\n"
            "Intervalle : <b>{interval}s</b>\n\n"
            "Choisissez ce que vous voulez modifier :"
        ),
        "cfg_route": "🛳️ Trajet aller",
        "cfg_date": "📅 Date aller",
        "cfg_route_ret": "🛳️ Trajet retour",
        "cfg_date_ret": "📅 Date retour",
        "cfg_triptype": "🔁 Type de voyage",
        "cfg_vehicle": "🚗 Véhicule",
        "cfg_pax": "👥 Passagers",
        "cfg_interval": "⏱️ Intervalle",
        "choose_route": "Choisissez le trajet aller :",
        "choose_route_ret": "Choisissez le trajet retour :",
        "choose_vehicle": "Choisissez le véhicule :",
        "choose_triptype": "Choisissez le type de voyage :",
        "oneway": "➡️ Aller simple",
        "return": "🔁 Aller-retour",
        "ask_date_ret": "Envoyez la date de retour au format <b>AAAA-MM-JJ</b>.",
        "trip_oneway": "Aller simple",
        "trip_return": "Aller-retour",
        "ask_date": "Envoyez la nouvelle date au format <b>AAAA-MM-JJ</b> (ex: 2026-10-16).",
        "ask_interval": "Envoyez le nouvel intervalle en secondes (minimum 10, recommandé 20).",
        "ask_adults": "Envoyez le nombre d'adultes.",
        "bad_date": "❌ Format invalide. Utilisez AAAA-MM-JJ.",
        "bad_number": "❌ Nombre invalide.",
        "saved": "✅ Enregistré.",
        "choose_lang": "🌐 Choisissez la langue :",
        "no_route": "⚠️ Trajet et date non configurés pour ce ticket. Allez dans Configurer.",
        "no_result": "Aucune donnée",
    },
    "ar": {
        "welcome": "🚢 <b>نوريس أليرت</b>\n\nبوت مراقبة تذاكر العبّارة.\nاختر تذكرة لإدارتها، أو اطّلع على السجل.",
        "menu": "📋 القائمة الرئيسية",
        "start": "▶️ بدء",
        "stop": "⏹️ إيقاف",
        "status": "📊 الحالة",
        "history": "📜 السجل",
        "config": "⚙️ إعدادات",
        "language": "🌐 اللغة",
        "started": "✅ التذكرة {n} : تمّ <b>تشغيل</b> المراقبة. فحص كل {interval} ثانية بدون توقّف حتى تتوفّر تذكرة.",
        "stopped": "⏹️ التذكرة {n} : تمّ <b>إيقاف</b> المراقبة.",
        "already_running": "⚠️ يعمل بالفعل.",
        "already_stopped": "⚠️ متوقّف بالفعل.",
        "ticket_num": "التذكرة {n}",
        "start_header": "▶️ أي تذكرة تريد بدء مراقبتها ؟",
        "stop_header": "⏹️ أي تذكرة تريد إيقافها ؟",
        "config_header": "⚙️ أي تذكرة تريد ضبطها ؟",
        "start_all": "▶️ بدء التذكرتين معًا",
        "stop_all": "⏹️ إيقاف التذكرتين معًا",
        "started_multi": "✅ تمّ تشغيل المراقبة لـ : {list}.",
        "stopped_multi": "⏹️ تمّ إيقاف المراقبة لـ : {list}.",
        "skipped_note": "⚠️ تمّ تجاهل التذكرة {n} (الرحلة/التاريخ غير مضبوطين).",
        "status_title": "📊 <b>الحالة — كل التذاكر</b>",
        "watch_body": (
            "🎫 <b>التذكرة {n}</b>\n\n"
            "الوضع : {state}\n"
            "الرحلة : {route}\n"
            "التاريخ : {date}\n"
            "المركبة : {vehicle}\n"
            "الفاصل الزمني : {interval} ثانية\n"
            "عدد الفحوصات : <b>{count}</b>\n"
            "آخر فحص : {last}\n"
            "آخر نتيجة : {last_result}"
        ),
        "state_running": "🟢 يعمل",
        "state_stopped": "🔴 متوقّف",
        "state_paused": "🟡 متوقّف مؤقتًا (تم العثور على تذكرة)",
        "never": "لم يحدث بعد",
        "history_title": "📜 <b>السجل</b> (آخر 20 فحصًا، كل التذاكر)",
        "history_empty": "لا توجد فحوصات مسجّلة بعد.",
        "ticket_found": (
            "🚨 <b>تذكرة متوفّرة — التذكرة {n} !</b> 🚨\n\n"
            "🚢 الرحلة : {route}\n"
            "📅 التاريخ : {date}\n\n"
            "🎫 <b>الرحلات :</b>\n<code>{sailings}</code>\n\n"
            "⚡ <i>احجز بسرعة قبل الآخرين !</i>"
        ),
        "book_now": "🎫 احجز الآن",
        "continue_search": "▶️ متابعة البحث",
        "stop_bot": "⏹️ إيقاف",
        "back_menu": "📋 القائمة",
        "config_body": (
            "⚙️ <b>إعدادات — التذكرة {n}</b>\n\n"
            "النوع : <b>{triptype}</b>\n"
            "الذهاب : <b>{route}</b> — <b>{date}</b>\n"
            "{return_line}"
            "المركبة : <b>{vehicle}</b>\n"
            "الركّاب : <b>{adults}ك / {children}ط / {infants}ر</b>\n"
            "الفاصل الزمني : <b>{interval} ث</b>\n\n"
            "اختر ما تريد تعديله :"
        ),
        "cfg_route": "🛳️ رحلة الذهاب",
        "cfg_date": "📅 تاريخ الذهاب",
        "cfg_route_ret": "🛳️ رحلة العودة",
        "cfg_date_ret": "📅 تاريخ العودة",
        "cfg_triptype": "🔁 نوع الرحلة",
        "cfg_vehicle": "🚗 المركبة",
        "cfg_pax": "👥 الركّاب",
        "cfg_interval": "⏱️ الفاصل الزمني",
        "choose_route": "اختر رحلة الذهاب :",
        "choose_route_ret": "اختر رحلة العودة :",
        "choose_vehicle": "اختر المركبة :",
        "choose_triptype": "اختر نوع الرحلة :",
        "oneway": "➡️ ذهاب فقط",
        "return": "🔁 ذهاب وإياب",
        "ask_date_ret": "أرسل تاريخ العودة بصيغة <b>YYYY-MM-DD</b>.",
        "trip_oneway": "ذهاب فقط",
        "trip_return": "ذهاب وإياب",
        "ask_date": "أرسل التاريخ الجديد بصيغة <b>YYYY-MM-DD</b> (مثال: 2026-10-16).",
        "ask_interval": "أرسل الفاصل الزمني الجديد بالثواني (الحد الأدنى 10، المستحسن 20).",
        "ask_adults": "أرسل عدد البالغين.",
        "bad_date": "❌ صيغة غير صالحة. استخدم YYYY-MM-DD.",
        "bad_number": "❌ رقم غير صالح.",
        "saved": "✅ تمّ الحفظ.",
        "choose_lang": "🌐 اختر اللغة :",
        "no_route": "⚠️ لم يتمّ ضبط الرحلة والتاريخ لهذه التذكرة. انتقل إلى الإعدادات.",
        "no_result": "لا توجد بيانات",
    },
}

STOP_EVENT = threading.Event()


def tr(cfg, key, **kw):
    lang = cfg.get("language", "fr")
    if lang not in T:
        lang = "fr"
    return T[lang][key].format(**kw)


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


_TLS = threading.local()


def _session():
    """requests.Session n'est PAS thread-safe : une session par thread
    (boucle Telegram + un worker par ticket) pour éviter que des réponses
    se croisent entre threads."""
    s = getattr(_TLS, "session", None)
    if s is None:
        s = requests.Session()
        s.verify = False
        _TLS.session = s
    return s


def tg_call(token, method, _timeout=15, _allow_retry=True, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, (dict, list)):
            data[k] = json.dumps(v, ensure_ascii=False)
        else:
            data[k] = v
    try:
        # (connect, read) explicites : un socket resté ouvert après une
        # suspension réseau du PC bloquait la boucle getUpdates pour de bon.
        r = _session().post(url, data=data, timeout=(10, _timeout))
        out = r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not out.get("ok"):
        desc = out.get("description") or ""
        retry_after = (out.get("parameters") or {}).get("retry_after")
        # 429 : Telegram impose une pause. Sans ça les réponses aux boutons
        # échouaient en silence quand on cliquait vite.
        if retry_after and _allow_retry:
            print(f"[{stamp()}] ⏳ 429 {method} — pause {retry_after}s", flush=True)
            time.sleep(min(int(retry_after) + 1, 30))
            return tg_call(token, method, _timeout=_timeout, _allow_retry=False, **params)
        # On NE log pas les answerCallbackQuery expirés : bruit inutile.
        if method != "answerCallbackQuery":
            print(f"[{stamp()}] ⚠ API {method}: {desc or out.get('error')}", flush=True)
    return out


def get_admin_ids(cfg):
    """Liste des chat IDs admin (dédupliquée)."""
    ids = []
    for v in cfg.get("telegram_chat_ids", []) or []:
        v = str(v).strip()
        if v and v not in ids:
            ids.append(v)
    single = str(cfg.get("telegram_chat_id", "")).strip()
    if single and single not in ids:
        ids.append(single)
    return ids


def send(cfg, text, reply_markup=None, chat_id=None):
    """Envoie à un chat précis, ou à TOUS les admins si chat_id est omis."""
    targets = [chat_id] if chat_id else get_admin_ids(cfg)
    results = []
    for cid in targets:
        results.append(tg_call(
            cfg["telegram_token"], "sendMessage",
            chat_id=cid,
            text=text, parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        ))
    return results[0] if results else {"ok": False}


def edit_msg(cfg, chat_id, message_id, text, reply_markup=None):
    r = tg_call(
        cfg["telegram_token"], "editMessageText",
        chat_id=chat_id,
        message_id=message_id,
        text=text, parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    if not r.get("ok"):
        desc = r.get("description") or r.get("error") or ""
        if "not modified" in desc.lower():
            send(cfg, text, reply_markup, chat_id=chat_id)
        else:
            print(f"[{stamp()}] ❌ edit erreur: {desc}", flush=True)
            send(cfg, text, reply_markup, chat_id=chat_id)
    return r


def answer_cb(cfg, callback_id, text=None):
    tg_call(cfg["telegram_token"], "answerCallbackQuery",
            callback_query_id=callback_id, text=text)


# ---------------------------------------------------------------------------
# État en mémoire (par ticket) + saisies en attente (par admin)
# ---------------------------------------------------------------------------
def _new_watch_state():
    return {
        "running": False,
        "paused_on_find": False,
        "last_search_at": 0.0,
        "last_check_time": None,
        "last_check_result": None,
        "checks_count": 0,
        "heartbeat": time.time(),
    }


STATE = {
    "watches": {wid: _new_watch_state() for wid in WATCH_IDS},
    "awaiting": {},  # chat_id(str) -> {"watch": "1", "field": "date"}
    "poll_heartbeat": None,  # dernier cycle getUpdates — surveillé par le watchdog
}


def wstate(wid):
    return STATE["watches"][wid]


def persist_running(cfg, wid):
    """Sauvegarde running/paused_on_find dans la config pour que la
    surveillance reprenne automatiquement après un redémarrage du process
    (crash, watchdog, mise en veille du PC) sans action de l'utilisateur."""
    w = get_watch(cfg, wid)
    st = wstate(wid)
    w["_running"] = st["running"]
    w["_paused_on_find"] = st["paused_on_find"]
    save_config(cfg)


def get_watch(cfg, wid):
    return cfg["watches"][wid]


def _esc(s):
    return html.escape(str(s), quote=False)


# ---------------------------------------------------------------------------
# Historique (combiné, tous tickets)
# ---------------------------------------------------------------------------
def record_history(entry):
    try:
        with HIST_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_history(n=20):
    if not HIST_FILE.exists():
        return []
    try:
        # On ne lit que la fin du fichier : il grossit sans limite (une ligne
        # toutes les ~15s) et "Historique" est le bouton le plus cliqué.
        with HIST_FILE.open("rb") as f:
            try:
                f.seek(-65536, os.SEEK_END)
                f.readline()  # jeter la 1re ligne probablement tronquée
            except OSError:
                f.seek(0)
            lines = f.read().decode("utf-8", errors="replace").strip().splitlines()
        out = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


def format_history(cfg):
    rows = read_history(20)
    if not rows:
        return tr(cfg, "history_empty")
    icon = {"AVAILABLE": "🟢", "UNAVAILABLE": "🔴", "UNKNOWN": "⚪", "ERROR": "⚠️"}
    wmark = {"1": "1️⃣", "2": "2️⃣"}
    lines = [tr(cfg, "history_title"), ""]
    for r in rows:
        ts = r.get("ts", "?")
        st = r.get("status", "UNKNOWN")
        wid = str(r.get("watch", "1"))
        lines.append(f"{wmark.get(wid, '•')} {icon.get(st,'•')} <code>{ts}</code> — {st}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Textes & claviers
# ---------------------------------------------------------------------------
def watch_line(cfg, wid):
    w = get_watch(cfg, wid)
    st = wstate(wid)
    if st["paused_on_find"]:
        icon = "🟡"
    elif st["running"]:
        icon = "🟢"
    else:
        icon = "🔴"
    route = w.get("outward_route") or "—"
    date = w.get("outward_date") or "—"
    return f"{icon} 🎫 {wid} — {route} — {date}"


def kb_main(cfg):
    """Menu principal — même structure que l'ancienne UX (1 ticket),
    chaque action ouvre maintenant un choix de ticket (tout / 1 / 2)."""
    rows = [
        [{"text": tr(cfg, "start"), "callback_data": "start_menu"},
         {"text": tr(cfg, "stop"), "callback_data": "stop_menu"}],
        [{"text": tr(cfg, "status"), "callback_data": "status"},
         {"text": tr(cfg, "history"), "callback_data": "history"}],
        [{"text": tr(cfg, "config"), "callback_data": "config_menu"}],
        [{"text": tr(cfg, "language"), "callback_data": "lang"}],
    ]
    return {"inline_keyboard": rows}


def kb_back(cfg):
    return {"inline_keyboard": [[{"text": tr(cfg, "back_menu"), "callback_data": "menu"}]]}


def kb_select(cfg, kind):
    """Sous-menu de sélection de ticket pour start / stop / config."""
    action = {"start": "wstart", "stop": "wstop", "config": "cfg"}[kind]
    rows = []
    if kind == "start":
        rows.append([{"text": tr(cfg, "start_all"), "callback_data": "startall"}])
    elif kind == "stop":
        rows.append([{"text": tr(cfg, "stop_all"), "callback_data": "stopall"}])
    for wid in WATCH_IDS:
        rows.append([{"text": watch_line(cfg, wid), "callback_data": f"{action}|{wid}"}])
    rows.append([{"text": tr(cfg, "back_menu"), "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def kb_found(cfg, wid):
    return {"inline_keyboard": [
        [{"text": tr(cfg, "book_now"), "url": BOOKING_URL}],
        [{"text": tr(cfg, "continue_search"), "callback_data": f"wcontinue|{wid}"}],
        [{"text": tr(cfg, "stop_bot"), "callback_data": f"wstop|{wid}"}],
        [{"text": tr(cfg, "back_menu"), "callback_data": "menu"}],
    ]}


def watch_text(cfg, wid):
    w = get_watch(cfg, wid)
    st = wstate(wid)
    if st["paused_on_find"]:
        state = tr(cfg, "state_paused")
    elif st["running"]:
        state = tr(cfg, "state_running")
    else:
        state = tr(cfg, "state_stopped")
    veh = next((k for k, v in VEHICLES_MAP.items() if v == w.get("vehicle", "")), "—")
    return tr(cfg, "watch_body",
              n=wid,
              state=_esc(state),
              route=_esc(w.get("outward_route") or "—"),
              date=_esc(w.get("outward_date") or "—"),
              vehicle=_esc(veh),
              interval=w.get("interval", 20),
              count=st["checks_count"],
              last=_esc(st["last_check_time"] or tr(cfg, "never")),
              last_result=_esc(st["last_check_result"] or tr(cfg, "no_result")))


def status_text_all(cfg):
    blocks = [watch_text(cfg, wid) for wid in WATCH_IDS]
    return tr(cfg, "status_title") + "\n\n" + "\n\n➖➖➖➖➖➖➖➖➖➖\n\n".join(blocks)


def config_text(cfg, wid):
    w = get_watch(cfg, wid)
    veh = next((k for k, v in VEHICLES_MAP.items() if v == w.get("vehicle", "")), "—")
    is_return = w.get("trip_type") == "return"
    triptype = tr(cfg, "trip_return" if is_return else "trip_oneway")
    if is_return:
        lang = cfg.get("language", "fr")
        lbl = "Retour" if lang == "fr" else "العودة"
        return_line = (f"{lbl} : <b>{_esc(w.get('return_route') or '—')}</b> — "
                       f"<b>{_esc(w.get('return_date') or '—')}</b>\n")
    else:
        return_line = ""
    return tr(cfg, "config_body",
              n=wid,
              triptype=_esc(triptype),
              route=_esc(w.get("outward_route") or "—"),
              date=_esc(w.get("outward_date") or "—"),
              return_line=return_line,
              vehicle=_esc(veh),
              adults=w.get("adults", 1),
              children=w.get("children", 0),
              infants=w.get("infants", 0),
              interval=w.get("interval", 20))


def kb_config(cfg, wid):
    w = get_watch(cfg, wid)
    rows = [
        [{"text": tr(cfg, "cfg_triptype"), "callback_data": f"cfg_triptype|{wid}"}],
        [{"text": tr(cfg, "cfg_route"), "callback_data": f"cfg_route|{wid}"},
         {"text": tr(cfg, "cfg_date"), "callback_data": f"cfg_date|{wid}"}],
    ]
    if w.get("trip_type") == "return":
        rows.append([{"text": tr(cfg, "cfg_route_ret"), "callback_data": f"cfg_route_ret|{wid}"},
                     {"text": tr(cfg, "cfg_date_ret"), "callback_data": f"cfg_date_ret|{wid}"}])
    rows += [
        [{"text": tr(cfg, "cfg_vehicle"), "callback_data": f"cfg_vehicle|{wid}"},
         {"text": tr(cfg, "cfg_pax"), "callback_data": f"cfg_pax|{wid}"}],
        [{"text": tr(cfg, "cfg_interval"), "callback_data": f"cfg_interval|{wid}"}],
        [{"text": tr(cfg, "back_menu"), "callback_data": "config_menu"}],
    ]
    return {"inline_keyboard": rows}


def kb_triptype(cfg, wid):
    return {"inline_keyboard": [
        [{"text": tr(cfg, "oneway"), "callback_data": f"settrip|{wid}|one-way"}],
        [{"text": tr(cfg, "return"), "callback_data": f"settrip|{wid}|return"}],
        [{"text": tr(cfg, "back_menu"), "callback_data": f"cfg|{wid}"}],
    ]}


def kb_routes(cfg, wid, ret=False):
    rows = []
    prefix = "setrouteret" if ret else "setroute"
    for name in ROUTES_MAP.keys():
        rows.append([{"text": name, "callback_data": f"{prefix}|{wid}|{name}"}])
    rows.append([{"text": tr(cfg, "back_menu"), "callback_data": f"cfg|{wid}"}])
    return {"inline_keyboard": rows}


def kb_vehicles(cfg, wid):
    rows = []
    for name, code in VEHICLES_MAP.items():
        label = name if len(name) < 40 else name[:37] + "…"
        rows.append([{"text": label, "callback_data": f"setveh|{wid}|{code}"}])
    rows.append([{"text": tr(cfg, "back_menu"), "callback_data": f"cfg|{wid}"}])
    return {"inline_keyboard": rows}


def kb_lang(cfg):
    return {"inline_keyboard": [
        [{"text": "🇫🇷 Français", "callback_data": "setlang|fr"},
         {"text": "🇸🇦 العربية", "callback_data": "setlang|ar"}],
        [{"text": tr(cfg, "back_menu"), "callback_data": "menu"}],
    ]}


# ---------------------------------------------------------------------------
# Traitement des updates Telegram
# ---------------------------------------------------------------------------
def handle_update(upd, cfg):
    admin_ids = get_admin_ids(cfg)
    if "callback_query" in upd:
        print(f"[{stamp()}] 👉 clic: {upd['callback_query'].get('data')}", flush=True)
    elif "message" in upd:
        print(f"[{stamp()}] 💬 msg: {(upd['message'].get('text') or '')[:40]}", flush=True)

    # Callback (bouton inline)
    if "callback_query" in upd:
        cb = upd["callback_query"]
        sender_id = str(cb["from"]["id"])
        if sender_id not in admin_ids:
            answer_cb(cfg, cb["id"], "Non autorisé.")
            return
        chat_id = str(cb["message"]["chat"]["id"])
        data = cb.get("data", "")
        msg_id = cb["message"]["message_id"]
        answer_cb(cfg, cb["id"])
        parts = data.split("|")
        action = parts[0]

        if action == "menu":
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "welcome"), kb_main(cfg))

        elif action == "start_menu":
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "start_header"), kb_select(cfg, "start"))

        elif action == "stop_menu":
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "stop_header"), kb_select(cfg, "stop"))

        elif action == "config_menu":
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "config_header"), kb_select(cfg, "config"))

        elif action == "status":
            edit_msg(cfg, chat_id, msg_id, status_text_all(cfg), kb_back(cfg))

        elif action == "wstart":
            wid = parts[1]
            w = get_watch(cfg, wid)
            st = wstate(wid)
            if st["running"] and not st["paused_on_find"]:
                edit_msg(cfg, chat_id, msg_id, tr(cfg, "already_running"), kb_main(cfg))
            elif not w.get("outward_date") or not w.get("outward_route"):
                edit_msg(cfg, chat_id, msg_id, tr(cfg, "no_route"), kb_main(cfg))
            else:
                st["running"] = True
                st["paused_on_find"] = False
                st["last_search_at"] = 0
                persist_running(cfg, wid)
                edit_msg(cfg, chat_id, msg_id,
                         tr(cfg, "started", n=wid, interval=w.get("interval", 20)),
                         kb_main(cfg))

        elif action == "wstop":
            wid = parts[1]
            st = wstate(wid)
            if not st["running"]:
                edit_msg(cfg, chat_id, msg_id, tr(cfg, "already_stopped"), kb_main(cfg))
            else:
                st["running"] = False
                st["paused_on_find"] = False
                persist_running(cfg, wid)
                edit_msg(cfg, chat_id, msg_id, tr(cfg, "stopped", n=wid), kb_main(cfg))

        elif action == "wcontinue":
            wid = parts[1]
            w = get_watch(cfg, wid)
            st = wstate(wid)
            st["paused_on_find"] = False
            st["running"] = True
            st["last_search_at"] = 0
            persist_running(cfg, wid)
            edit_msg(cfg, chat_id, msg_id,
                     tr(cfg, "started", n=wid, interval=w.get("interval", 20)),
                     kb_main(cfg))

        elif action == "startall":
            started, skipped = [], []
            for wid in WATCH_IDS:
                w = get_watch(cfg, wid)
                st = wstate(wid)
                if not w.get("outward_date") or not w.get("outward_route"):
                    skipped.append(wid)
                    continue
                st["running"] = True
                st["paused_on_find"] = False
                st["last_search_at"] = 0
                persist_running(cfg, wid)
                started.append(wid)
            text = tr(cfg, "started_multi", list=", ".join(started) or "—")
            if skipped:
                text += "\n" + "\n".join(tr(cfg, "skipped_note", n=s) for s in skipped)
            edit_msg(cfg, chat_id, msg_id, text, kb_main(cfg))

        elif action == "stopall":
            for wid in WATCH_IDS:
                st = wstate(wid)
                st["running"] = False
                st["paused_on_find"] = False
                persist_running(cfg, wid)
            text = tr(cfg, "stopped_multi", list=", ".join(WATCH_IDS))
            edit_msg(cfg, chat_id, msg_id, text, kb_main(cfg))

        elif action == "history":
            edit_msg(cfg, chat_id, msg_id, format_history(cfg), kb_back(cfg))

        elif action == "cfg":
            wid = parts[1]
            edit_msg(cfg, chat_id, msg_id, config_text(cfg, wid), kb_config(cfg, wid))

        elif action == "lang":
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "choose_lang"), kb_lang(cfg))

        elif action == "setlang":
            lang = parts[1]
            cfg["language"] = lang if lang in T else "fr"
            save_config(cfg)
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "welcome"), kb_main(cfg))

        elif action == "cfg_route":
            wid = parts[1]
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "choose_route"), kb_routes(cfg, wid))

        elif action == "setroute":
            wid, route = parts[1], parts[2]
            if route in ROUTES_MAP:
                get_watch(cfg, wid)["outward_route"] = route
                save_config(cfg)
            edit_msg(cfg, chat_id, msg_id, config_text(cfg, wid), kb_config(cfg, wid))

        elif action == "cfg_vehicle":
            wid = parts[1]
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "choose_vehicle"), kb_vehicles(cfg, wid))

        elif action == "setveh":
            wid, code = parts[1], parts[2]
            if code in VEHICLES_MAP.values():
                get_watch(cfg, wid)["vehicle"] = code
                save_config(cfg)
            edit_msg(cfg, chat_id, msg_id, config_text(cfg, wid), kb_config(cfg, wid))

        elif action == "cfg_date":
            wid = parts[1]
            STATE["awaiting"][chat_id] = {"watch": wid, "field": "date"}
            send(cfg, tr(cfg, "ask_date"), chat_id=chat_id)

        elif action == "cfg_date_ret":
            wid = parts[1]
            STATE["awaiting"][chat_id] = {"watch": wid, "field": "date_ret"}
            send(cfg, tr(cfg, "ask_date_ret"), chat_id=chat_id)

        elif action == "cfg_route_ret":
            wid = parts[1]
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "choose_route_ret"), kb_routes(cfg, wid, ret=True))

        elif action == "setrouteret":
            wid, route = parts[1], parts[2]
            if route in ROUTES_MAP:
                get_watch(cfg, wid)["return_route"] = route
                save_config(cfg)
            edit_msg(cfg, chat_id, msg_id, config_text(cfg, wid), kb_config(cfg, wid))

        elif action == "cfg_triptype":
            wid = parts[1]
            edit_msg(cfg, chat_id, msg_id, tr(cfg, "choose_triptype"), kb_triptype(cfg, wid))

        elif action == "settrip":
            wid, tt = parts[1], parts[2]
            if tt in ("one-way", "return"):
                get_watch(cfg, wid)["trip_type"] = tt
                save_config(cfg)
            edit_msg(cfg, chat_id, msg_id, config_text(cfg, wid), kb_config(cfg, wid))

        elif action == "cfg_interval":
            wid = parts[1]
            STATE["awaiting"][chat_id] = {"watch": wid, "field": "interval"}
            send(cfg, tr(cfg, "ask_interval"), chat_id=chat_id)

        elif action == "cfg_pax":
            wid = parts[1]
            STATE["awaiting"][chat_id] = {"watch": wid, "field": "adults"}
            send(cfg, tr(cfg, "ask_adults"), chat_id=chat_id)

        return

    # Message texte
    if "message" in upd:
        msg = upd["message"]
        sender_id = str(msg.get("from", {}).get("id", ""))
        if sender_id not in admin_ids:
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return

        # Commandes
        if text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd in ("/start", "/menu", "/help"):
                send(cfg, tr(cfg, "welcome"), kb_main(cfg), chat_id=sender_id)
                STATE["awaiting"].pop(sender_id, None)
            return

        # Entrée en attente pour CET admin ?
        aw = STATE["awaiting"].get(sender_id)
        if not aw:
            send(cfg, tr(cfg, "welcome"), kb_main(cfg), chat_id=sender_id)
            return

        wid, field = aw["watch"], aw["field"]
        w = get_watch(cfg, wid)

        if field == "date":
            try:
                datetime.strptime(text, "%Y-%m-%d")
                w["outward_date"] = text
                save_config(cfg)
                STATE["awaiting"].pop(sender_id, None)
                send(cfg, tr(cfg, "saved"), chat_id=sender_id)
                send(cfg, config_text(cfg, wid), kb_config(cfg, wid), chat_id=sender_id)
            except Exception:
                send(cfg, tr(cfg, "bad_date"), chat_id=sender_id)
        elif field == "date_ret":
            try:
                datetime.strptime(text, "%Y-%m-%d")
                w["return_date"] = text
                save_config(cfg)
                STATE["awaiting"].pop(sender_id, None)
                send(cfg, tr(cfg, "saved"), chat_id=sender_id)
                send(cfg, config_text(cfg, wid), kb_config(cfg, wid), chat_id=sender_id)
            except Exception:
                send(cfg, tr(cfg, "bad_date"), chat_id=sender_id)
        elif field == "interval":
            try:
                v = max(10, int(text))
                w["interval"] = v
                save_config(cfg)
                STATE["awaiting"].pop(sender_id, None)
                send(cfg, tr(cfg, "saved"), chat_id=sender_id)
                send(cfg, config_text(cfg, wid), kb_config(cfg, wid), chat_id=sender_id)
            except Exception:
                send(cfg, tr(cfg, "bad_number"), chat_id=sender_id)
        elif field == "adults":
            try:
                w["adults"] = max(1, int(text))
                save_config(cfg)
                STATE["awaiting"].pop(sender_id, None)
                send(cfg, tr(cfg, "saved"), chat_id=sender_id)
                send(cfg, config_text(cfg, wid), kb_config(cfg, wid), chat_id=sender_id)
            except Exception:
                send(cfg, tr(cfg, "bad_number"), chat_id=sender_id)


# ---------------------------------------------------------------------------
# Boucle de travail — un thread Playwright indépendant par ticket
# ---------------------------------------------------------------------------
def worker_loop(cfg, wid):
    """Thread séparé : gère Playwright et exécute les vérifications pour UN ticket."""
    with sync_playwright() as pw:
        def _new_browser():
            b = pw.chromium.launch(headless=cfg.get("headless", True))
            p = b.new_page(viewport={"width": 1280, "height": 900})
            p.set_default_timeout(30000)
            return b, p

        browser, page = _new_browser()
        try:
            while not STOP_EVENT.is_set():
                w = get_watch(cfg, wid)
                st = wstate(wid)
                now = time.time()
                st["heartbeat"] = now
                interval = max(10, int(w.get("interval", 20)))
                if (st["running"] and not st["paused_on_find"]
                        and now - st["last_search_at"] >= interval):
                    st["last_search_at"] = now
                    st["checks_count"] += 1
                    n = st["checks_count"]
                    print(f"[{stamp()}] 🔎 Ticket {wid} — vérification #{n}", flush=True)

                    status = "ERROR"
                    sailings_str = ""
                    try:
                        text, result_url = fill_and_submit(page, w)
                        status = classify_result(text, result_url, target_date=w.get("outward_date"))
                        if status == "AVAILABLE":
                            sailings = extract_sailings(text, only_available=True, target_date=w.get("outward_date"))
                            sailings_str = "\n".join([f"• {_esc(s)}" for s in sailings])
                    except Exception as e:
                        print(f"[{stamp()}] erreur ticket {wid}: {e}", flush=True)
                        # Browser/page may be in a broken state — recreate it.
                        try:
                            browser.close()
                        except Exception:
                            pass
                        time.sleep(15)
                        try:
                            browser, page = _new_browser()
                        except Exception as e2:
                            print(f"[{stamp()}] browser restart failed: {e2}", flush=True)
                            time.sleep(30)
                            continue

                    ts_now = stamp()
                    st["last_check_time"] = ts_now
                    st["last_check_result"] = status
                    record_history({
                        "ts": ts_now, "status": status, "n": n, "watch": wid,
                        "route": w.get("outward_route"),
                        "date": w.get("outward_date"),
                    })
                    print(f"[{stamp()}] → Ticket {wid}: {status}", flush=True)

                    # Pas de notification pour UNAVAILABLE — tout reste dans l'historique.
                    if status == "AVAILABLE":
                        st["paused_on_find"] = True
                        st["running"] = False
                        persist_running(cfg, wid)
                        try:
                            send(cfg,
                                 tr(cfg, "ticket_found",
                                    n=wid,
                                    route=_esc(w.get("outward_route")),
                                    date=_esc(w.get("outward_date")),
                                    sailings=sailings_str or "—"),
                                 kb_found(cfg, wid))
                        except Exception as e:
                            print(f"[{stamp()}] alert send error: {e}", flush=True)

                time.sleep(0.5)
        finally:
            try:
                browser.close()
            except Exception:
                pass


# Mesuré sur 427 vérifications réelles : médiane 10s, pire cas 45s.
# 240s laisse passer une vérification lente sans tuer le process pour rien,
# mais rattrape un driver Playwright définitivement bloqué.
WATCHDOG_STALL_SECONDS = 240


POLL_STALL_SECONDS = 180  # getUpdates long-poll = 20s : 180s sans un seul cycle = boucle bloquée


def _drop_stale_backlog(token):
    """Telegram rejoue TOUTES les mises à jour non confirmées des 24 dernières
    heures quand on démarre avec offset=0. Après chaque redémarrage le bot
    rejouait donc tous les anciens clics (anciens menus renvoyés, anciens
    wstart/wstop réappliqués) et n'avait plus le temps de répondre aux
    nouveaux clics — c'était la cause des boutons qui ne répondent plus.
    Un clic d'avant le redémarrage n'a aucune valeur : on les jette."""
    resp = tg_call(token, "getUpdates", offset=-1, timeout=0, _timeout=20)
    if resp.get("ok"):
        results = resp.get("result") or []
        if results:
            offset = results[-1]["update_id"] + 1
            print(f"[{stamp()}] 🧹 backlog Telegram ignoré — reprise à offset={offset}", flush=True)
            return offset
        print(f"[{stamp()}] 🧹 aucun backlog Telegram en attente", flush=True)
        return 0
    print(f"[{stamp()}] ⚠ impossible de lire l'offset Telegram ({resp.get('description') or resp.get('error')}) — démarrage à 0", flush=True)
    return 0


def _watchdog_loop():
    """Surveille les threads workers ET la boucle Telegram. Un thread
    Playwright coincé (pipe driver mort après la mise en veille du PC, etc.)
    ou une boucle getUpdates bloquée sur une socket morte ne peuvent pas être
    interrompus proprement depuis Python — on tue tout le processus pour
    qu'un superviseur externe le relance à neuf plutôt que de rester planté
    en silence indéfiniment."""
    while not STOP_EVENT.is_set():
        time.sleep(15)
        now = time.time()
        for wid in WATCH_IDS:
            st = wstate(wid)
            age = now - st.get("heartbeat", now)
            if age > WATCHDOG_STALL_SECONDS:
                print(f"[{stamp()}] 💀 watchdog: ticket {wid} bloqué depuis {age:.0f}s — redémarrage forcé du processus", flush=True)
                time.sleep(0.2)  # laisser le temps au print/flush avant de tuer
                os._exit(1)

        # Les tickets peuvent tourner parfaitement pendant que les boutons
        # sont morts : il faut surveiller la boucle Telegram séparément.
        beat = STATE.get("poll_heartbeat")
        if beat:
            age = now - beat
            if age > POLL_STALL_SECONDS:
                print(f"[{stamp()}] 💀 watchdog: boucle Telegram bloquée depuis {age:.0f}s — redémarrage forcé du processus", flush=True)
                time.sleep(0.2)
                os._exit(1)


def _pid_alive(pid):
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def _refuse_if_already_running():
    """Deux instances pollant le même bot Telegram se marchent dessus
    (réponses dupliquées/erratiques). Filet de sécurité si tg_control.py
    est lancé directement en plus du superviseur."""
    lock = BASE / "tg_control.lock"
    if lock.exists():
        try:
            other = int(lock.read_text().strip())
        except Exception:
            other = None
        if other and other != os.getpid() and _pid_alive(other):
            print(f"[{stamp()}] ⚠ une instance tourne déjà (pid={other}) — arrêt.", flush=True)
            sys.exit(1)
    lock.write_text(str(os.getpid()), encoding="utf-8")


def run():
    _refuse_if_already_running()
    cfg = load_config()
    token = cfg.get("telegram_token")
    admin_ids = get_admin_ids(cfg)
    if not token or not admin_ids:
        print("⚠ telegram_token / telegram_chat_id(s) manquants dans la config")
        sys.exit(1)

    # Reprise automatique de la surveillance après un redémarrage (crash,
    # watchdog, mise en veille du PC) — sans ça il fallait recliquer
    # "démarrer" dans Telegram à chaque fois.
    resumed = []
    for wid in WATCH_IDS:
        w = get_watch(cfg, wid)
        st = wstate(wid)
        st["running"] = bool(w.get("_running"))
        st["paused_on_find"] = bool(w.get("_paused_on_find"))
        st["last_search_at"] = 0
        if st["running"] and not st["paused_on_find"]:
            resumed.append(wid)

    print(f"[{stamp()}] 🤖 Démarrage du bot Telegram piloté — admins {admin_ids} — tickets {WATCH_IDS}"
          + (f" — reprise auto: {resumed}" if resumed else ""), flush=True)

    send(cfg, tr(cfg, "welcome"), kb_main(cfg))

    # Un thread Playwright indépendant par ticket pour garder la précision de chacun.
    workers = []
    for wid in WATCH_IDS:
        t = threading.Thread(target=worker_loop, args=(cfg, wid), daemon=True)
        t.start()
        workers.append(t)

    threading.Thread(target=_watchdog_loop, daemon=True).start()

    offset = _drop_stale_backlog(token)
    polls = 0
    last_beat = 0.0
    try:
        while True:
            try:
                resp = tg_call(token, "getUpdates", offset=offset, timeout=20, _timeout=35)
                STATE["poll_heartbeat"] = time.time()
                polls += 1
                if resp.get("ok"):
                    for upd in resp.get("result", []):
                        offset = upd["update_id"] + 1
                        try:
                            handle_update(upd, cfg)
                        except Exception as e:
                            print(f"[{stamp()}] handle_update error: {e}", flush=True)
                        STATE["poll_heartbeat"] = time.time()
                else:
                    # Réseau coupé OU erreur API (409 conflit, token, ...).
                    # Sans cette pause la boucle martelait l'API à vide.
                    time.sleep(5)

                # Preuve de vie des boutons dans le log (toutes les 5 min) :
                # si cette ligne continue, la boucle Telegram répond.
                if time.time() - last_beat >= 300:
                    last_beat = time.time()
                    print(f"[{stamp()}] ♥ boucle Telegram vivante — {polls} sondages, offset={offset}", flush=True)
            except Exception as e:
                print(f"[{stamp()}] getUpdates error: {e}", flush=True)
                time.sleep(5)
    except KeyboardInterrupt:
        print(f"\n[{stamp()}] 🛑 Arrêt demandé.", flush=True)
    finally:
        STOP_EVENT.set()
        for t in workers:
            t.join(timeout=5)


if __name__ == "__main__":
    run()
