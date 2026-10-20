"""
Start Bot — Direct Launcher for Nouris Alert.
Starts monitoring & Telegram alerts immediately without showing the menu!
"""
import sys
from nouris_bot import load_config, monitor, stamp

if __name__ == "__main__":
    cfg = load_config()
    if not cfg.get("outward_date"):
        print("⚠ Veuillez configurer la date et le trajet au moins une fois.")
        sys.exit(1)
    
    print(f"[{stamp()}] 🚀 DÉMARRAGE IMMÉDIAT DU BOT TELEGRAM...")
    print(f"  Trajet: {cfg.get('outward_route')} | Date: {cfg.get('outward_date')}")
    print(f"  Telegram: {cfg.get('telegram_chat_id')} | Intervalle: {cfg.get('interval')}s\n")
    
    try:
        monitor(cfg)
    except KeyboardInterrupt:
        print("\nArrêté par l'utilisateur.")
