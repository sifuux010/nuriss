"""
Watchdog — relance automatiquement tg_control.py s'il tombe.
"""
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PYTHON = BASE / ".venv" / "Scripts" / "python.exe"
BOT = BASE / "tg_control.py"
LOG = BASE / "tg_control.log"
ERR = BASE / "tg_control_err.log"

RESTART_DELAY = 10  # secondes avant relance


def run():
    proc = None
    while True:
        if proc is None or proc.poll() is not None:
            code = proc.returncode if proc else "N/A"
            print(f"[watchdog] Bot arrêté (code={code}), relance dans {RESTART_DELAY}s...", flush=True)
            time.sleep(RESTART_DELAY)
            with open(LOG, "a") as out, open(ERR, "a") as err:
                proc = subprocess.Popen(
                    [str(PYTHON), str(BOT)],
                    cwd=str(BASE),
                    stdout=out,
                    stderr=err,
                )
            print(f"[watchdog] Bot démarré — PID {proc.pid}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    print("[watchdog] Démarrage du watchdog Nouris Alert", flush=True)
    run()
