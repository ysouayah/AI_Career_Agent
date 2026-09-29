"""
Refresh the Handshake session the extractor uses.

    python handshake_auth.py

A normal browser window opens. Log in to Handshake the usual way (BU single sign-on + Duo).
The script notices when your Handshake dashboard loads and saves the session by itself; if it
doesn't notice within 3 minutes, it asks you to press Enter instead.

Writes two files -- NEVER commit either (both are in .gitignore):
  handshake_state.json   the session, for running the extractor on this laptop
  handshake_state.b64    the same session compressed, to paste into the GitHub secret
                         HANDSHAKE_STATE (Settings -> Secrets and variables -> Actions)
Anyone holding either file is logged in to your Handshake account.
"""
import base64
import gzip
import json

from playwright.sync_api import sync_playwright

STATE_FILE = "handshake_state.json"
SECRET_FILE = "handshake_state.b64"
SECRET_LIMIT = 48 * 1024   # GitHub's maximum secret size


def keep(domain):
    # Only what Handshake needs to recognise the login. Ad and analytics cookies (LinkedIn,
    # TikTok, Bing, DoubleClick...) made the old file too big for a GitHub secret.
    return "joinhandshake.com" in domain or "bu.edu" in domain


LOGIN_MARKERS = ("/login", "shib.bu.edu", "duosecurity", "/sso", "sign_in")


def on_dashboard(url):
    return "joinhandshake.com" in (url or "") and not any(m in url for m in LOGIN_MARKERS) \
        and ("/explore" in url or "/home" in url or "/job-search" in url or "/postings" in url)


def wait_for_login(context, timeout_s=180):
    """Watch EVERY tab: BU sign-on or the school picker can finish the login in a new tab,
    so the tab this script opened may never leave the login page."""
    import time
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if any(on_dashboard(pg.url) for pg in context.pages):
            return True
        time.sleep(2)
    return False


def session_works(context):
    """The real test: a brand-new tab that goes to Handshake without being sent to login."""
    probe = context.new_page()
    try:
        probe.goto("https://app.joinhandshake.com/explore", wait_until="domcontentloaded", timeout=45000)
        probe.wait_for_timeout(3000)
        return not any(m in probe.url for m in LOGIN_MARKERS), probe.url
    finally:
        probe.close()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()
        page.goto("https://app.joinhandshake.com/login")
        print("\nLog in to Handshake in the browser window (select Boston University, then BU login + Duo).")
        if wait_for_login(context):
            print("Dashboard detected.")
        else:
            input("Didn't detect the dashboard. Once you're logged in and see Handshake, press Enter... ")
        ok, landed = session_works(context)
        if not ok:
            print(f"Handshake still sends a fresh tab to the login page ({landed}).")
            print("The login didn't stick. Log in again, then run this script again.")
            browser.close()
            return
        print("Session verified in a fresh tab.")
        state = context.storage_state()
        browser.close()

    slim = {"cookies": [c for c in state["cookies"] if keep(c["domain"])],
            "origins": [o for o in state["origins"] if "joinhandshake.com" in o["origin"]]}
    with open(STATE_FILE, "w") as f:
        json.dump(slim, f)
    encoded = base64.b64encode(gzip.compress(json.dumps(slim).encode())).decode()
    with open(SECRET_FILE, "w") as f:
        f.write(encoded)

    print(f"\nSaved {STATE_FILE} ({len(slim['cookies'])} cookies) and {SECRET_FILE} ({len(encoded):,} chars).")
    if len(encoded) > SECRET_LIMIT:
        print("!!! Too large for a GitHub secret -- send me the size and I'll trim further. !!!")
    else:
        print(f"Next: copy the contents of {SECRET_FILE} into the GitHub secret HANDSHAKE_STATE.")
        print("On a Mac:  pbcopy < handshake_state.b64   (then paste into the secret)")


if __name__ == "__main__":
    main()