import asyncio
import json
import os
import random
import re
import urllib.parse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

STATE_FILE = "handshake_state.json"
OUTPUT_FILE = "handshake_jobs.json"
STATUS_FILE = "handshake_status.json"   # read by run_everything.py to warn in the report
MAX_PAGES = 5

# Handshake has used both /jobs/<id> and /job-search/<id>; match either, by numeric id.
JOB_LINK = re.compile(r"/(?:jobs|job-search)/(\d+)")
# Where Handshake sends a browser whose session has expired.
LOGIN_MARKERS = ("/login", "shib.bu.edu", "duosecurity", "/sso", "sign_in")


def job_id(href):
    m = JOB_LINK.search(href or "")
    return m.group(1) if m else None


def canonical_url(origin, jid):
    """One URL per job. Search pages append ?query=...&page=..., which made the same job look
    like several different URLs and slipped past the dedupe."""
    return f"{origin}/jobs/{jid}"


def looks_logged_out(url):
    return any(marker in (url or "") for marker in LOGIN_MARKERS)


def write_status(ok, message):
    with open(STATUS_FILE, "w") as f:
        json.dump({"ok": ok, "message": message}, f)


async def extract_job_data():
    print("--- INITIATING HANDSHAKE EXTRACTION ---")

    try:
        with open("search_targets.json", "r") as f:
            data = json.load(f)
        titles = data.get("titles")
        locations = data.get("locations", ["United States"])
        if not titles:
            print("Error: 'titles' key is missing or empty in search_targets.json.")
            return
    except FileNotFoundError:
        print("Error: search_targets.json not found. Please run brainstormer.py first.")
        return

    if not os.path.exists(STATE_FILE):
        # Handshake job search requires a login; without a session every query returns nothing.
        print(f"!!! {STATE_FILE} not found. Handshake search requires a login -- skipping Handshake. !!!")
        with open(OUTPUT_FILE, "w") as f:
            json.dump([], f)
        write_status(False, "no Handshake session available")
        return

    jobs_by_id = {}
    session_expired = False
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=STATE_FILE,
                                            viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        target_location = locations[0] if locations else ""
        print(f"Loaded {len(titles)} target titles. Up to {MAX_PAGES} pages per query.")

        for q_index, title in enumerate(titles):
            query = urllib.parse.quote(title)
            loc = f"&location={urllib.parse.quote(target_location)}" if target_location else ""
            url = f"https://bu.joinhandshake.com/job-search?query={query}{loc}"
            print(f"\n-> Searching: {title}")
            found_for_query = 0
            try:
                # networkidle rarely fires on Handshake (analytics keep the network busy), so each
                # query used to time out and be skipped. Load the DOM, then wait for job links.
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)

                if looks_logged_out(page.url):
                    print("!!! Handshake session has expired: redirected to the login page. !!!")
                    print(f"!!! Run handshake_auth.py and update the HANDSHAKE_STATE secret. !!!")
                    session_expired = True
                    break

                origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(page.url))
                for page_num in range(1, MAX_PAGES + 1):
                    try:
                        await page.wait_for_selector("a[href*='/jobs/'], a[href*='/job-search/']", timeout=20000)
                    except PlaywrightTimeout:
                        shot = f"handshake_debug_q{q_index}_p{page_num}.png"
                        await page.screenshot(path=shot, full_page=True)
                        print(f"   No job links found on page {page_num} (url: {page.url}). Saved {shot}.")
                        break
                    await page.wait_for_timeout(random.uniform(3500, 6200))

                    for element in await page.locator("a[href*='/jobs/'], a[href*='/job-search/']").all():
                        href = await element.get_attribute("href")
                        jid = job_id(href)
                        if not jid:
                            continue
                        lines = [l.strip() for l in (await element.inner_text()).split("\n") if l.strip()]
                        if len(lines) >= 2 and jid not in jobs_by_id:
                            jobs_by_id[jid] = {"query_matched": title, "raw_text": lines,
                                               "url": canonical_url(origin, jid), "source": "Handshake"}
                            found_for_query += 1

                    if page_num == MAX_PAGES:
                        break
                    next_button = page.locator("button[aria-label*='Next' i], button:has-text('Next')").first
                    if await next_button.count() and await next_button.is_visible() and not await next_button.is_disabled():
                        await next_button.click()
                        await page.wait_for_load_state("domcontentloaded")
                    else:
                        break
            except Exception as e:
                print(f"!!! Error on query '{title}': {e} !!!")
            print(f"   {found_for_query} new job(s) from this query.")

        await browser.close()

    jobs = list(jobs_by_id.values())
    print(f"\n====================================")
    print(f"Handshake: {len(jobs)} unique job(s) extracted.")
    print(f"====================================\n")
    with open(OUTPUT_FILE, "w") as f:
        json.dump(jobs, f, indent=4)
    if session_expired:
        write_status(False, "Handshake session expired")
    else:
        write_status(True, f"{len(jobs)} job(s) extracted")


if __name__ == "__main__":
    asyncio.run(extract_job_data())