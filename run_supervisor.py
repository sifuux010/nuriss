"""
Supervisor — relance tg_control.py automatiquement s'il plante, se bloque
(watchdog interne -> os._exit) ou meurt après une mise en veille du PC.
Usage : python run_supervisor.py   (le laisser tourner dans un terminal,
ou le lancer au démarrage de Windows via le Planificateur de tâches).
"""
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG_FILE = BASE / "tg_control.log"
ERR_FILE = BASE / "tg_control_err.log"
LOCK_FILE = BASE / "run_supervisor.lock"

MIN_BACKOFF = 5
MAX_BACKOFF = 60


def _pid_alive(pid):
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_singleton_lock():
    """Empêche deux superviseurs (et donc deux bots pollant le même token
    Telegram) de tourner en même temps, ce qui provoque des réponses
    dupliquées/erratiques dans Telegram."""
    if LOCK_FILE.exists():
        try:
            other_pid = int(LOCK_FILE.read_text().strip())
        except Exception:
            other_pid = None
        if other_pid and _pid_alive(other_pid):
            print(f"[{stamp()}] 🧭 superviseur déjà actif (pid={other_pid}) — arrêt.", flush=True)
            sys.exit(0)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_line(msg):
    line = f"[{stamp()}] {msg}\n"
    print(line, end="", flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def main():
    _acquire_singleton_lock()
    backoff = MIN_BACKOFF
    while True:
        log_line("🧭 superviseur: démarrage de tg_control.py")
        started_at = time.time()
        with LOG_FILE.open("a", encoding="utf-8") as out, ERR_FILE.open("a", encoding="utf-8") as err:
            proc = subprocess.Popen(
                [sys.executable, str(BASE / "tg_control.py")],
                cwd=str(BASE), stdout=out, stderr=err,
            )
            code = proc.wait()

        ran_for = time.time() - started_at
        log_line(f"🧭 superviseur: tg_control.py s'est arrêté (code={code}, durée={ran_for:.0f}s)")

        # Si le process a tenu longtemps avant de tomber, on repart tout de
        # suite ; s'il crashe en boucle rapidement, on ralentit (backoff).
        if ran_for > 120:
            backoff = MIN_BACKOFF
        else:
            backoff = min(MAX_BACKOFF, backoff * 2)

        log_line(f"🧭 superviseur: nouvelle tentative dans {backoff}s")
        time.sleep(backoff)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_line("🧭 superviseur: arrêt demandé.")
