import asyncio
import json
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

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
        if handshake_jobs:
            print("-> Unlocking Handshake deep links...")
            context_hs = await browser.new_context(storage_state="handshake_state.json")
            page_hs = await context_hs.new_page()
            
            for job in handshake_jobs:
                try:
                    await page_hs.goto(job['url'], wait_until="domcontentloaded")
                    await page_hs.wait_for_timeout(2000)
                    
                    # Grab ALL the text on the page
                    text = await page_hs.locator("body").inner_text()
                    # We cap it at 4000 characters so we just get the job description, not the page footers
                    job['full_description'] = text[:4000] 
                    deep_results.append(job)
                    print(f"   [+] Scraped: {job.get('title', 'Handshake Job')}")
                except Exception as e:
                    print(f"   [-] Failed to load Handshake job: {e}")
                    
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
                    
                    text = await page_pub.locator("body").inner_text()
                    job['full_description'] = text[:4000]
                    deep_results.append(job)
                    print(f"   [+] Scraped: {job.get('title', 'Public Job')}")
                except Exception as e:
                    print(f"   [-] Failed to load public job: {e}")
                    
            await context_pub.close()

        await browser.close()

    print(f"\nSuccess! Extracted {len(deep_results)} full job descriptions.")
    
    with open("deep_jobs.json", "w") as f:
        json.dump(deep_results, f, indent=4)

if __name__ == "__main__":
    asyncio.run(scrape_deep_links())