"""
Point d'entrée pour l'hébergement (Hugging Face Spaces / tout environnement Docker).
Lance le bot Telegram dans un thread et expose un petit serveur web de santé
(obligatoire sur HF Spaces, qui attend un port HTTP ouvert).
"""
import os
import threading
from flask import Flask

import tg_control

app = Flask(__name__)
_status = {"running": False}


@app.route("/")
def health():
    return {
        "service": "nouris-alert",
        "bot_thread_alive": _status["running"],
    }


def start_bot():
    _status["running"] = True
    try:
        tg_control.run()
    except BaseException as e:
        print(f"bot thread mort: {type(e).__name__}: {e}", flush=True)
    finally:
        _status["running"] = False
        # Sans ça, Flask continuait de répondre "OK" alors que le bot était
        # mort : le conteneur paraissait sain et personne ne le relançait.
        # On tue le process pour que Docker (--restart=always) reparte à neuf.
        os._exit(1)


if __name__ == "__main__":
    t = threading.Thread(target=start_bot, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)
