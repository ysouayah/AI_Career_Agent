import asyncio
import json
import urllib.parse
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

    # Check if a custom cookies/state file exists, default to base handshake if not
    storage_state_file = "handshake_state.json"
    has_auth = os.path.exists(storage_state_file)
    
    # Base URL handling: If you are running it, it uses your saved state. 
    # If someone else runs it without a state file, it gracefully hits standard public Handshake.
    base_domain = "bu.joinhandshake.com" if has_auth else "joinhandshake.com"

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        
        # Load storage state only if it actually exists locally
        if has_auth:
            context = await browser.new_context(storage_state=storage_state_file, viewport={'width': 1920, 'height': 1080})
        else:
            print("Warning: handshake_state.json not found. Attempting public domain search.")
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
            
        page = await context.new_page()
        all_jobs_list = []
        
        print(f"Loaded {len(titles)} target titles. Starting Handshake scrape...")

        # 2. Loop through every AI-generated title
        for title in titles:
            encoded_query = urllib.parse.quote(title)
            
            # If a location was extracted, append it to the query parameters
            target_location = locations[0] if locations else ""
            loc_param = f"&location={urllib.parse.quote(target_location)}" if target_location else ""
            
            target_url = f"https://{base_domain}/job-search?query={encoded_query}{loc_param}"
            
            print(f"-> Searching: {title}")
            try:
                await page.goto(target_url, wait_until="networkidle")
                await page.wait_for_timeout(5000) 
                
                job_elements = await page.locator("a[href*='/jobs/']").all()
                
                for element in job_elements:
                    text = await element.inner_text()
                    href = await element.get_attribute("href")
                    
                    if text.strip() and href:
                        lines = [line.strip() for line in text.split('\n') if line.strip()]
                        if len(lines) >= 2:
                            # Build correct clean links structurally
                            full_link = f"https://{base_domain}{href}" if href.startswith('/') else href
                            all_jobs_list.append({
                                "query_matched": title,
                                "raw_text": lines,
                                "url": full_link,
                                "source": "Handshake"
                            })
            except Exception as e:
                print(f"!!! Handshake block encountered or timeout for query '{title}': {e} !!!")
                continue
        
        unique_jobs = list({job['url']: job for job in all_jobs_list}.values())
        print(f"\nSuccess! Extracted {len(unique_jobs)} total Handshake jobs.")
        
        with open("handshake_jobs.json", "w") as f:
            json.dump(unique_jobs, f, indent=4)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(extract_job_data())