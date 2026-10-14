import asyncio
import json
import urllib.parse
import random
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# LinkedIn's own filters: f_JT=F full-time, f_E=2 entry level. Without them most results were
# 3-7-year roles that the rules then threw away, crowding real matches out of the top 80.
LINKEDIN_FILTERS = "&f_JT=F&f_E=2"
# Spring-internship track: f_JT=I internships only, fewer pages. Cards are tagged so the card
# stage routes them to their own pool and they never displace a full-time job.
LINKEDIN_INTERN_FILTERS = "&f_JT=I"
MAX_INTERN_PAGES = 2

async def scrape_linkedin():
    print("--- INITIATING LINKEDIN EXTRACTION ---")
    
    # 1. Grab targets from the Brainstormer
    try:
        with open("search_targets.json", "r") as f:
            data = json.load(f)
            titles = data.get("titles")
            intern_titles = data.get("internship_titles") or []
            locations = data.get("locations", ["United States"])
            
        if not titles or len(titles) == 0:
            print("Error: 'titles' key is missing or empty in search_targets.json.")
            return
            
    except FileNotFoundError:
        print("Error: search_targets.json not found. Please run brainstormer.py first.")
        return

    # Use the first location the AI extracted
    target_location = locations[0] if locations else "United States"
    encoded_location = urllib.parse.quote(target_location)

    # MAXIMUM PAGES TO SCRAPE PER QUERY (LinkedIn loads 25 jobs per page)
    MAX_PAGES = 5

    # 2. Start the Scraper
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        # Adding a specific User-Agent helps bypass the LinkedIn Auth-Wall
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        all_jobs_list = []
        print(f"Loaded {len(titles)} target titles. Starting LinkedIn scrape with {MAX_PAGES}-page depth limit...")

        # 3. Loop through every title: the full-time searches, then the internship searches
        searches = ([(t, LINKEDIN_FILTERS, MAX_PAGES, None) for t in titles]
                    + [(t, LINKEDIN_INTERN_FILTERS, MAX_INTERN_PAGES, "internship") for t in intern_titles])
        for title, filters, max_pages, track in searches:
            encoded_query = urllib.parse.quote(title)
            print(f"\n-> Searching: {title}" + (" (internships)" if track else ""))
            
            # --- PAGINATION LOOP START ---
            for page_num in range(0, max_pages):
                # LinkedIn increments by 25 (Page 1 = 0, Page 2 = 25, Page 3 = 50...)
                start_param = page_num * 25
                target_url = (f"https://www.linkedin.com/jobs/search?keywords={encoded_query}"
                              f"&location={encoded_location}{filters}&start={start_param}")
                
                print(f"   [Scraping Page {page_num + 1}]")
                
                try:
                    await page.goto(target_url, wait_until="domcontentloaded")
                    
                    # Generous randomized delay to prevent Auth-Wall redirects (4.5 to 8.2 seconds)
                    human_delay = random.uniform(4500, 8200)
                    await page.wait_for_timeout(human_delay) 
                    
                    job_cards = await page.locator("ul.jobs-search__results-list > li").all()
                    
                    # If the page yields no cards, we've hit the end of the search results
                    if not job_cards:
                        print(f"   No more listings found on this page. Moving to next query.")
                        break
                    
                    for card in job_cards:
                        text = await card.inner_text()
                        link_element = card.locator("a[href*='/jobs/view/']").first
                        
                        if await link_element.count() > 0:
                            href = await link_element.get_attribute("href")
                            clean_url = href.split('?')[0] if href else ""
                            
                            if text.strip() and clean_url:
                                lines = [line.strip() for line in text.split('\n') if line.strip()]
                                if len(lines) >= 2:
                                    job = {
                                        "query_matched": title,
                                        "raw_text": lines,
                                        "url": clean_url,
                                        "source": "LinkedIn"
                                    }
                                    if track:
                                        job["track"] = track
                                    all_jobs_list.append(job)
                                    
                except Exception as page_error:
                    print(f"   !!! Error scanning page {page_num + 1}: {page_error} !!!")
                    break # Break pagination loop on failure to protect current list
            # --- PAGINATION LOOP END ---
        
        # Deduplicate jobs by URL
        # A job found by a full-time search stays untagged even if an internship search finds it too.
        by_url = {}
        for job in all_jobs_list:
            if job['url'] not in by_url or not job.get('track'):
                by_url[job['url']] = job
        unique_jobs = list(by_url.values())
        print(f"\n====================================")
        print(f"Success! Deep-extracted {len(unique_jobs)} total LinkedIn jobs.")
        print(f"====================================\n")
        
        with open("linkedin_jobs.json", "w") as f:
            json.dump(unique_jobs, f, indent=4)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_linkedin())