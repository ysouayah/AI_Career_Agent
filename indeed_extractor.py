import asyncio
import json
import urllib.parse
import random
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# Indeed's own filters: full-time, entry level. Same reason as LinkedIn's.
INDEED_FILTERS = "&jt=fulltime&sc=0kf%3Aexplvl%28ENTRY_LEVEL%29%3B"
# Spring-internship track: internships only, fewer pages, cards tagged for their own pool.
INDEED_INTERN_FILTERS = "&jt=internship"
MAX_INTERN_PAGES = 2
# Target-company searches ("<title> <company>" from search_targets.json): run last, 1 page each,
# same full-time + entry-level filters. Additive only: their cards are tagged found_by
# "target_company" and never replace a card a title search already found.
MAX_PAGES = 5   # pages per title search
MAX_COMPANY_PAGES = 1


def plan_searches(data):
    """(query, filters, pages, track, found_by) in run order: title searches exactly as before,
    then internship searches, then target-company searches."""
    titles = data.get("titles") or []
    intern_titles = data.get("internship_titles") or []
    company = [q["query"] for q in (data.get("company_queries") or [])
               if isinstance(q, dict) and str(q.get("query") or "").strip()]
    return ([(t, INDEED_FILTERS, MAX_PAGES, None, None) for t in titles]
            + [(t, INDEED_INTERN_FILTERS, MAX_INTERN_PAGES, "internship", None) for t in intern_titles]
            + [(q, INDEED_FILTERS, MAX_COMPANY_PAGES, None, "target_company") for q in company])

async def scrape_indeed():
    print("--- INITIATING INDEED EXTRACTION ---")
    
    # 1. Grab targets from the Autonomous Brainstormer
    try:
        with open("search_targets.json", "r") as f:
            data = json.load(f)
            titles = data.get("titles")
            intern_titles = data.get("internship_titles") or []
            locations = data.get("locations", ["United States"])
            searches = plan_searches(data)
            
        if not titles or len(titles) == 0:
            print("Error: 'titles' key is missing or empty in search_targets.json.")
            return
            
    except FileNotFoundError:
        print("Error: search_targets.json not found. Please run brainstormer.py first.")
        return

    # Use the first location extracted by the AI
    target_location = locations[0] if locations else "United States"
    encoded_location = urllib.parse.quote_plus(target_location)

    # 2. Start the Scraper natively on your residential IP
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        all_jobs_list = []
        print(f"Loaded {len(titles)} target titles. Starting Indeed scrape with {MAX_PAGES}-page depth limit...")

        # 3. Loop through every title: the full-time searches, then the internship searches
        for title, filters, max_pages, track, found_by in searches:
            encoded_query = urllib.parse.quote_plus(title)
            print(f"\n-> Searching: {title}" + (" (internships)" if track else "")
                  + (" (target company)" if found_by else ""))
            
            # --- PAGINATION LOOP START ---
            for page_num in range(0, max_pages):
                # Indeed increments pages by 10 items (Page 1 = 0, Page 2 = 10, Page 3 = 20...)
                start_param = page_num * 10
                target_url = (f"https://www.indeed.com/jobs?q={encoded_query}&l={encoded_location}"
                              f"{filters}&start={start_param}")
                
                print(f"   [Scraping Page {page_num + 1}]")
                
                try:
                    await page.goto(target_url, wait_until="domcontentloaded")
                    
                    # Generous randomized delay between page shifts to prevent Cloudflare flags (4.2 to 8.5 seconds)
                    human_delay = random.uniform(4200, 8500)
                    await page.wait_for_timeout(human_delay)
                    
                    # Extract via direct structural DOM selectors
                    job_cards = await page.locator("td.resultContent").all()
                    
                    # If a page contains no job cards, we've exhausted search results early
                    if not job_cards:
                        print(f"   No more listings found on this page. Moving to next query.")
                        break
                        
                    for card in job_cards:
                        text = await card.inner_text()
                        link_element = card.locator("a[id^='job_']").first
                        
                        if await link_element.count() > 0:
                            href = await link_element.get_attribute("href")
                            clean_url = f"https://www.indeed.com{href}" if href.startswith('/') else href
                            
                            if text.strip() and clean_url:
                                lines = [line.strip() for line in text.split('\n') if line.strip()]
                                if len(lines) >= 2:
                                    job = {
                                        "query_matched": title,
                                        "raw_text": lines,
                                        "url": clean_url,
                                        "source": "Indeed"
                                    }
                                    if track:
                                        job["track"] = track
                                    if found_by:
                                        job["found_by"] = found_by
                                    all_jobs_list.append(job)
                                    
                except Exception as page_error:
                    print(f"   !!! Error scanning page {page_num + 1}: {page_error} !!!")
                    break # Break pagination loop on failure to protect current list
            # --- PAGINATION LOOP END ---
        
        # Deduplicate results by URL
        # A job found by a full-time search stays untagged even if an internship search finds it too.
        by_url = {}
        # A target-company card is kept only if no other search found that URL.
        for job in all_jobs_list:
            if job.get('found_by') == 'target_company':
                if job['url'] not in by_url:
                    by_url[job['url']] = job
            elif job['url'] not in by_url or not job.get('track'):
                by_url[job['url']] = job
        unique_jobs = list(by_url.values())
        print(f"\n====================================")
        print(f"Success! Deep-extracted {len(unique_jobs)} total Indeed jobs.")
        print(f"====================================\n")
        
        with open("indeed_jobs.json", "w") as f:
            json.dump(unique_jobs, f, indent=4)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_indeed())