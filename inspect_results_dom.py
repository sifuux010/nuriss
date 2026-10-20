"""
Inspect results page HTML structure for Marseille -> Algiers 2026-10-16
"""
from playwright.sync_api import sync_playwright
import json

URL = "https://booking.nouriselbahrferries.com/en/book/journey/journeySearch/"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(URL, wait_until="networkidle")

    # Set one-way
    page.evaluate("""() => {
        const rad = document.querySelector('input[name="bookingflow"][value="ONEWAY"]');
        if (rad) { rad.checked = true; rad.dispatchEvent(new Event('change', {bubbles: true})); }
    }""")

    # Set route P~MRS-P~ALG
    page.evaluate("""() => {
        const sel = document.querySelector('select[name="cw_journeysearch_j1_route"]');
        if (sel) { sel.value = "P~MRS-P~ALG"; sel.dispatchEvent(new Event('change', {bubbles: true})); }
    }""")
    page.wait_for_timeout(1000)

    # Set date 2026-10-16
    page.evaluate("""() => {
        const inp = document.querySelector('input[name="cw_journeysearch_j1_date"]');
        if (inp) {
            inp.classList.remove('date-sold-out');
            inp.value = '2026-10-16';
            inp.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }""")

    # Set 1 adult 12 chd
    page.evaluate("""() => {
        const adl = document.querySelector('select[name="cw_journeysearch_j1_passengers[1][qty]"]');
        if (adl) adl.value = "1";
        const chd = document.querySelector('select[name="cw_journeysearch_j1_passengers[2][qty]"]');
        if (chd) chd.value = "12";
    }""")

    # Set numJrys 1
    page.evaluate("""() => {
        const h = document.querySelector('input[name="cw_journeysearch_numJrys"]');
        if (h) h.value = '1';
    }""")

    # Submit
    page.evaluate("""() => {
        const btn = document.querySelector('button.cw-action-next[type="submit"]');
        if (btn) btn.click();
    }""")

    page.wait_for_timeout(5000)
    print("URL after submit:", page.url)

    # Dump HTML of journey containers / rows
    html_info = page.evaluate("""() => {
        const info = {};
        info.url = window.location.href;
        info.bodyText = document.body.innerText;

        // Collect all potential journey / sailing elements
        const rows = Array.from(document.querySelectorAll('.cw-journey, .cw-journey-item, .cw-journey-row, tr, .journey, .sailing, div[class*="journey"], div[class*="sailing"]'));
        info.elements = rows.map(r => ({
            tag: r.tagName,
            className: r.className,
            id: r.id,
            text: r.innerText.trim().replace(/\\s+/g, ' ')
        })).filter(e => e.text.length > 5 && e.text.length < 500);

        return info;
    }""")

    with open("results_dom_dump.json", "w", encoding="utf-8") as f:
        json.dump(html_info, f, indent=2, ensure_ascii=False)

    print("Saved DOM dump to results_dom_dump.json")
    print("\nBody text snippet:")
    print(html_info["bodyText"][:1500])

    browser.close()
