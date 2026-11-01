"""
Screenshot every expanded question card on the SlackAHead study portal.

How it works: it attaches to a Chrome window YOU started and signed in to
(so Google login never touches this script), expands each card, saves one
PNG per card, then clicks Next and repeats until there are no more pages.

Setup (once):
    pip install playwright
    (no `playwright install` needed, we use your real Chrome)

Run:
    1. Start Chrome with remote debugging (separate profile folder):
         Windows:
           "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
             --remote-debugging-port=9222 --user-data-dir="C:\\pw-profile"
         macOS:
           /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
             --remote-debugging-port=9222 --user-data-dir=/tmp/pw-profile
    2. In that window: sign in with Google, open the page that lists your
       mistakes, apply any filters, and make sure you're on page 1.
    3. python shoot_questions.py
    4. Close that Chrome window when done (port 9222 gives local control
       of the browser while it's open).
"""

import re
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

CDP_URL = "http://localhost:9222"
OUT_DIR = Path("mistake_shots")
LABEL = "Show question & answer"          # text on each card's toggle
NEXT_BTN = re.compile(r"next", re.I)      # adjust if the pager uses something else
SETTLE_MS = 800                           # wait after expanding (math rendering)

# Tags the i-th toggle and its card in the DOM so Playwright can target them.
# The card is the highest ancestor that still contains only that one toggle.
# Returns the total number of toggles currently on the page.
TAG_JS = """
([label, i]) => {
  const isToggle = el =>
    el.textContent.trim() === label &&
    ![...el.children].some(c => c.textContent.trim() === label);
  const all = [...document.querySelectorAll('body *')].filter(isToggle);
  document.querySelectorAll('[data-shot-card],[data-shot-toggle]').forEach(e => {
    e.removeAttribute('data-shot-card');
    e.removeAttribute('data-shot-toggle');
  });
  if (i >= all.length) return all.length;
  const toggle = all[i];
  let card = toggle;
  while (
    card.parentElement &&
    card.parentElement !== document.body &&
    all.filter(t => card.parentElement.contains(t)).length === 1
  ) {
    card = card.parentElement;
  }
  toggle.setAttribute('data-shot-toggle', '');
  card.setAttribute('data-shot-card', '');
  return all.length;
}
"""


def tag(page, i):
    return page.evaluate(TAG_JS, [LABEL, i])


def process_page(page, seen, counter, page_no):
    """Expand + screenshot every card on the current page. Returns new counter."""
    total = tag(page, 10**6)  # count only, tags nothing
    print(f"Page {page_no}: {total} cards found")

    for i in range(total):
        tag(page, i)
        card = page.locator("[data-shot-card]")
        toggle = card.locator("[data-shot-toggle]")
        card.scroll_into_view_if_needed()

        key = card.inner_text()[:120]
        if key in seen:               # already captured (e.g. repeated page)
            continue
        seen.add(key)

        box = card.bounding_box()
        before = box["height"] if box else 0
        toggle.click()
        page.wait_for_timeout(400)

        # If the card shrank, it was already open and we just closed it.
        tag(page, i)
        box = card.bounding_box()
        after = box["height"] if box else 0
        if after < before - 5:
            toggle.click()
            page.wait_for_timeout(400)
            tag(page, i)

        page.wait_for_timeout(SETTLE_MS)
        counter += 1
        path = OUT_DIR / f"q{counter:03d}_p{page_no}.png"
        card.screenshot(path=str(path))
        print(f"  saved {path.name}")

    return counter


def main():
    OUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = next(
            (pg for pg in context.pages if "slackahead.com" in pg.url),
            context.pages[0],
        )
        page.bring_to_front()
        page.set_viewport_size({"width": 1100, "height": 900})

        seen, counter, page_no = set(), 0, 1
        while True:
            counter = process_page(page, seen, counter, page_no)

            nxt = page.get_by_role("button", name=NEXT_BTN).first
            if nxt.count() == 0 or not nxt.is_enabled():
                break

            old_text = page.inner_text("body")
            nxt.click()
            try:
                page.wait_for_function(
                    "old => document.body.innerText !== old",
                    arg=old_text,
                    timeout=10_000,
                )
            except PWTimeout:
                print("Next did not change the page, stopping.")
                break
            page.wait_for_timeout(1000)
            page_no += 1

        print(f"Done: {counter} screenshots in {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
