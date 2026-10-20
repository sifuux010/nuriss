"""Quick test: fill form, submit, capture result page text."""
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://booking.nouriselbahrferries.com/en/book/journey/journeySearch/"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    # Use a large viewport to avoid "outside of viewport" errors
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.set_default_timeout(30000)

    print("Loading booking page...")
    resp = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    print(f"HTTP {resp.status if resp else '?'}")
    page.wait_for_timeout(2000)

    # Accept cookies via JS
    page.evaluate("""() => {
        const btn = document.querySelector('.cw-accept-cookies');
        if (btn) btn.click();
    }""")
    page.wait_for_timeout(500)

    # 1. Set trip type to one-way via JS (avoids viewport issues)
    page.evaluate("""() => {
        const radio = document.getElementById('cw-bookingflow-ONEWAY');
        if (radio) {
            radio.checked = true;
            radio.dispatchEvent(new Event('change', {bubbles: true}));
            radio.dispatchEvent(new Event('click', {bubbles: true}));
            // Also click the label to trigger the site's jQuery handlers
            const label = document.querySelector('label[for="cw-bookingflow-ONEWAY"]');
            if (label) label.click();
        }
    }""")
    page.wait_for_timeout(1000)

    # 2. Select route: Algiers - Alicante
    page.evaluate("""() => {
        const sel = document.querySelector('select[name="cw_journeysearch_j1_route"]');
        if (sel) {
            sel.value = 'P~ALG-P~ALC';
            sel.dispatchEvent(new Event('change', {bubbles: true}));
            // Trigger jQuery change
            if (typeof jQuery !== 'undefined') {
                jQuery(sel).trigger('change');
            }
        }
    }""")
    page.wait_for_timeout(1000)

    # 3. Set date via JS on the hidden input
    page.evaluate("""() => {
        const dateInput = document.querySelector('input[name="cw_journeysearch_j1_date"]');
        if (dateInput) {
            // Remove sold-out class
            dateInput.classList.remove('date-sold-out');
            dateInput.value = '2026-11-15';
            dateInput.dispatchEvent(new Event('change', {bubbles: true}));
            if (typeof jQuery !== 'undefined') {
                jQuery(dateInput).trigger('change');
            }
        }
    }""")
    page.wait_for_timeout(500)

    # Also click the calendar day if visible (the site uses a custom calendar)
    # First navigate to November
    month_selects = page.locator('select.cw-change-month').first
    if month_selects.count():
        month_selects.select_option(value="2026-11")
        page.wait_for_timeout(1500)
    
    # Try to click a day in the calendar
    try:
        day_cell = page.locator('.cw-calendar-day:not(.cw-day-disabled):not(.cw-day-sold-out)').first
        if day_cell.count():
            day_cell.click(timeout=3000)
            page.wait_for_timeout(500)
    except Exception as e:
        print(f"Calendar click: {e}")

    # Check what date was set
    date_val = page.evaluate("""() => {
        const d = document.querySelector('input[name="cw_journeysearch_j1_date"]');
        return d ? {value: d.value, className: d.className} : null;
    }""")
    print(f"Date field after setting: {date_val}")

    # 4. Set passengers: 1 adult
    page.evaluate("""() => {
        const sel = document.querySelector('select[name="cw_journeysearch_j1_passengers[1][qty]"]');
        if (sel) {
            sel.value = '1';
            sel.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }""")

    # 5. Set numJrys to 1 for one-way
    page.evaluate("""() => {
        const h = document.querySelector('input[name="cw_journeysearch_numJrys"]');
        if (h) h.value = '1';
    }""")

    # Print the form state before submission
    print("\n=== FORM STATE ===")
    form_state = page.evaluate("""() => {
        const data = {};
        data.bookingflow = document.querySelector('input[name="bookingflow"]:checked')?.value;
        data.route = document.querySelector('select[name="cw_journeysearch_j1_route"]')?.value;
        data.date = document.querySelector('input[name="cw_journeysearch_j1_date"]')?.value;
        data.date_class = document.querySelector('input[name="cw_journeysearch_j1_date"]')?.className;
        data.adults = document.querySelector('select[name="cw_journeysearch_j1_passengers[1][qty]"]')?.value;
        data.numJrys = document.querySelector('input[name="cw_journeysearch_numJrys"]')?.value;
        return data;
    }""")
    for k, v in form_state.items():
        print(f"  {k}: {v}")

    # 6. Submit the form by clicking the Next button via JS
    print("\n=== SUBMITTING FORM ===")
    page.evaluate("""() => {
        const btn = document.querySelector('button.cw-action-next[type="submit"]');
        if (btn) btn.click();
    }""")

    # Wait for navigation/results
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except PlaywrightTimeoutError:
        print("Load state timeout (page may have loaded anyway)")
    
    page.wait_for_timeout(4000)

    print(f"\n=== RESULT PAGE ===")
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")

    body_text = page.locator("body").inner_text()
    print(f"\n=== BODY TEXT ({len(body_text)} chars) ===")
    print(body_text[:8000])

    # Check for specific elements
    print("\n\n=== CHECKING KEY ELEMENTS ===")
    checks = page.evaluate("""() => {
        const body = document.body.innerText.toLowerCase();
        return {
            has_no_journeys: body.includes('no journeys'),
            has_select_journey: body.includes('select your journey') || body.includes('choose your journey'),
            has_error: body.includes('error') || body.includes('unavailable'),
            has_sold_out: body.includes('sold out') || body.includes('sold-out'),
            has_departed: body.includes('departed'),
            has_journey_list: document.querySelectorAll('.cw-journey-option, .cw-sailing, .cw-journey-row, [class*="journey"]').length,
            errors_div: document.querySelector('.cw-journeysearch-errors')?.innerText?.trim() || '',
            validation_errors: Array.from(document.querySelectorAll('.error, .cw-error, .validation-error, [class*="error"]')).map(e => e.innerText.trim()).filter(t => t).slice(0, 10),
            url: window.location.href,
        };
    }""")
    for k, v in checks.items():
        print(f"  {k}: {v}")

    browser.close()
    print("\nDone.")
