"""Diagnostic: dump le texte brut de la page de résultats."""
import sys
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright
from nouris_bot import load_config, fill_and_submit, classify_result, extract_sailings

cfg = load_config()
print(f"Config: {cfg['outward_route']} | {cfg['outward_date']} | vehicle={cfg['vehicle']} | adults={cfg['adults']}")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.set_default_timeout(30000)
    try:
        text, url = fill_and_submit(page, cfg)
        print(f"\n=== URL RÉSULTAT ===\n{url}")
        print(f"\n=== CLASSIFY ===\n{classify_result(text, url)}")
        print(f"\n=== TOUS SAILINGS (dispo + indispo) ===")
        for s in extract_sailings(text, only_available=False):
            print(f"  → {s}")
        print(f"\n=== SAILINGS DISPO SEULEMENT ===")
        for s in extract_sailings(text, only_available=True):
            print(f"  → {s}")
        print(f"\n=== EXTRAIT TEXTE PAGE (1500 car.) ===")
        print(text[:1500])
    finally:
        browser.close()
