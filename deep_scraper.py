import asyncio
import json
import os
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

HANDSHAKE_STATE = "handshake_state.json"
LOGIN_MARKERS = ("/login", "shib.bu.edu", "duosecurity", "/sso", "sign_in")


async def page_text(page, min_chars=1500, max_wait_ms=10000):
    """Handshake and LinkedIn render descriptions after the page loads; a fixed 2 s wait
    sometimes captured only the page shell. Wait until the text stops being tiny."""
    waited, text = 0, ""
    while waited <= max_wait_ms:
        text = await page.locator("body").inner_text()
        if len(text) >= min_chars:
            break
        await page.wait_for_timeout(1000)
        waited += 1000
    return text


def keep_unscraped(job, results, why):
    """A job that couldn't be read stays in the batch with an empty description, so the
    pipeline logs it as a retry and tries again next run instead of silently dropping it."""
    job["full_description"] = ""
    job["scrape_error"] = why
    results.append(job)

async def scrape_deep_links():
    try:
        with open("sifted_jobs.json", "r") as f:
            jobs = json.load(f)
    except FileNotFoundError:
        print("Error: sifted_jobs.json not found.")
        return

    print(f"\n[Deep Scraper] Initiating deep dive on {len(jobs)} high-priority targets...")
    
    # Split the jobs because Handshake needs authentication, the others need anonymity
    handshake_jobs = [j for j in jobs if j.get('source') == 'Handshake']
    public_jobs = [j for j in jobs if j.get('source') in ['LinkedIn', 'Indeed']]

    deep_results = []

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)

        # 1. Process Handshake Jobs (Authenticated)
        if handshake_jobs and not os.path.exists(HANDSHAKE_STATE):
            # Without a session every page is a login screen. Keep the jobs for next run
            # rather than crashing the whole scraper (which lost every job, not just these).
            print(f"-> {HANDSHAKE_STATE} not found; keeping {len(handshake_jobs)} Handshake job(s) for next run.")
            for job in handshake_jobs:
                keep_unscraped(job, deep_results, "no Handshake session")
        elif handshake_jobs:
            print("-> Unlocking Handshake deep links...")
            context_hs = await browser.new_context(storage_state=HANDSHAKE_STATE)
            page_hs = await context_hs.new_page()
            session_dead = False

            for job in handshake_jobs:
                if session_dead:
                    keep_unscraped(job, deep_results, "Handshake session expired")
                    continue
                try:
                    await page_hs.goto(job['url'], wait_until="domcontentloaded")
                    if any(m in page_hs.url for m in LOGIN_MARKERS):
                        # A login page is not a job description; never hand it to the grader.
                        print("   [!] Handshake session expired -- remaining Handshake jobs kept for next run.")
                        session_dead = True
                        keep_unscraped(job, deep_results, "Handshake session expired")
                        continue
                    text = await page_text(page_hs)
                    # 12k keeps the tail of long postings, where qualifications and
                    # years-of-experience requirements usually live.
                    job['full_description'] = text[:12000]
                    deep_results.append(job)
                    print(f"   [+] Scraped: {job.get('title', 'Handshake Job')} ({len(text):,} chars)")
                except Exception as e:
                    print(f"   [-] Failed to load Handshake job: {e}")
                    keep_unscraped(job, deep_results, f"load failed: {e}")

            await context_hs.close()

        # 2. Process LinkedIn/Indeed Jobs (Anonymous)
        if public_jobs:
            print("-> Unlocking public deep links (giving servers time to breathe)...")
            context_pub = await browser.new_context(viewport={'width': 1920, 'height': 1080})
            page_pub = await context_pub.new_page()
            
            for job in public_jobs:
                try:
                    await page_pub.goto(job['url'], wait_until="domcontentloaded")
                    # We add a longer 3-second pause so Indeed doesn't flag us as a bot
                    await page_pub.wait_for_timeout(3000)

                    text = await page_text(page_pub)
                    job['full_description'] = text[:12000]
                    deep_results.append(job)
                    print(f"   [+] Scraped: {job.get('title', 'Public Job')} ({len(text):,} chars)")
                except Exception as e:
                    print(f"   [-] Failed to load public job: {e}")
                    keep_unscraped(job, deep_results, f"load failed: {e}")
                    
            await context_pub.close()

        await browser.close()

    readable = sum(1 for j in deep_results if j.get("full_description"))
    print(f"\nExtracted {readable} full job descriptions; {len(deep_results) - readable} kept for retry.")
    
    with open("deep_jobs.json", "w") as f:
        json.dump(deep_results, f, indent=4)

if __name__ == "__main__":
    asyncio.run(scrape_deep_links())