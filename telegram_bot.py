"""
Telegram Bot Launcher — Directly starts the Telegram ferry monitoring bot.
"""
import sys
from nouris_bot import load_config, monitor, stamp

if __name__ == "__main__":
    cfg = load_config()
    if not cfg.get("outward_date"):
        print("⚠ Veuillez d'abord configurer la date et le trajet.")
        sys.exit(1)
    
    print(f"[{stamp()}] 📱 DÉMARRAGE IMMÉDIAT DE LA SURVEILLANCE TELEGRAM")
    print(f"  Destination : {cfg.get('outward_route')}")
    print(f"  Date        : {cfg.get('outward_date')}")
    print(f"  Telegram ID : {cfg.get('telegram_chat_id')}\n")

    try:
        monitor(cfg)
    except KeyboardInterrupt:
        print("\nArrêté par l'utilisateur.")
