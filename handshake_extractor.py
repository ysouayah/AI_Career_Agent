import asyncio
import json
import urllib.parse
import random
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import os

async def extract_job_data():
    print("--- INITIATING HANDSHAKE EXTRACTION ---")
    
    # 1. Grab targets from the Autonomous Brainstormer
    try:
        with open("search_targets.json", "r") as f:
            data = json.load(f)
            titles = data.get("titles")
            locations = data.get("locations", ["United States"])
            
        if not titles or len(titles) == 0:
            print("Error: 'titles' key is missing or empty in search_targets.json.")
            return
            
    except FileNotFoundError:
        print("Error: search_targets.json not found. Please run brainstormer.py first.")
        return

    storage_state_file = "handshake_state.json"
    has_auth = os.path.exists(storage_state_file)
    
    base_domain = "bu.joinhandshake.com" if has_auth else "joinhandshake.com"
    
    # MAXIMUM PAGES TO SCRAPE PER QUERY (Adjust this to scale up or down)
    MAX_PAGES = 5

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        
        if has_auth:
            context = await browser.new_context(storage_state=storage_state_file, viewport={'width': 1920, 'height': 1080})
        else:
            print("Warning: handshake_state.json not found. Attempting public domain search.")
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
            
        page = await context.new_page()
        all_jobs_list = []
        
        print(f"Loaded {len(titles)} target titles. Starting Handshake scrape with {MAX_PAGES}-page depth limit...")

        # 2. Loop through every AI-generated title
        for title in titles:
            encoded_query = urllib.parse.quote(title)
            target_location = locations[0] if locations else ""
            loc_param = f"&location={urllib.parse.quote(target_location)}" if target_location else ""
            target_url = f"https://{base_domain}/job-search?query={encoded_query}{loc_param}"
            
            print(f"\n-> Searching: {title}")
            
            try:
                await page.goto(target_url, wait_until="networkidle")
                
                # --- PAGINATION LOOP START ---
                for page_num in range(1, MAX_PAGES + 1):
                    # Randomized delay to mimic human reading speed (3.5 to 6.2 seconds)
                    human_delay = random.uniform(3500, 6200)
                    await page.wait_for_timeout(human_delay)
                    
                    print(f"   [Scraping Page {page_num}]")
                    job_elements = await page.locator("a[href*='/jobs/']").all()
                    
                    for element in job_elements:
                        text = await element.inner_text()
                        href = await element.get_attribute("href")
                        
                        if text.strip() and href:
                            lines = [line.strip() for line in text.split('\n') if line.strip()]
                            if len(lines) >= 2:
                                full_link = f"https://{base_domain}{href}" if href.startswith('/') else href
                                all_jobs_list.append({
                                    "query_matched": title,
                                    "raw_text": lines,
                                    "url": full_link,
                                    "source": "Handshake"
                                })
                    
                    # Check if we have hit the max pages before trying to click next
                    if page_num == MAX_PAGES:
                        print(f"   Max page limit ({MAX_PAGES}) reached for this query.")
                        break
                        
                    # Attempt to find and click the "Next" button
                    # Uses multiple CSS strategies to catch different Handshake DOM versions
                    next_button = page.locator("button[aria-label*='Next' i], button:has-text('Next')").first
                    
                    if await next_button.is_visible() and not await next_button.is_disabled():
                        await next_button.click()
                        await page.wait_for_load_state("networkidle")
                    else:
                        print(f"   No more pages available for this query.")
                        break # Break the pagination loop if there is no next page
                # --- PAGINATION LOOP END ---

            except Exception as e:
                print(f"!!! Handshake block encountered or timeout for query '{title}': {e} !!!")
                continue
        
        unique_jobs = list({job['url']: job for job in all_jobs_list}.values())
        print(f"\n====================================")
        print(f"Success! Deep-extracted {len(unique_jobs)} total Handshake jobs.")
        print(f"====================================\n")
        
        with open("handshake_jobs.json", "w") as f:
            json.dump(unique_jobs, f, indent=4)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(extract_job_data())