import asyncio
import json
import urllib.parse
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def scrape_linkedin():
    print("--- INITIATING LINKEDIN EXTRACTION ---")
    
    # 1. Grab targets from the Brainstormer
    try:
        with open("search_targets.json", "r") as f:
            data = json.load(f)
            titles = data.get("titles", ["Data Analyst"])
            locations = data.get("locations", ["United States"])
    except FileNotFoundError:
        print("Warning: search_targets.json not found. Using default targets.")
        titles = ["Data Analyst"]
        locations = ["United States"]

    # Use the first location the AI extracted
    target_location = locations[0] if locations else "United States"
    encoded_location = urllib.parse.quote(target_location)

    # 2. Start the Scraper
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()
        
        all_jobs_list = []
        print(f"Loaded {len(titles)} target titles for location: '{target_location}'.")

        # 3. Loop through every title the AI generated
        for title in titles:
            encoded_query = urllib.parse.quote(title)
            
            # The dynamic URL using both Title and Location
            target_url = f"https://www.linkedin.com/jobs/search?keywords={encoded_query}&location={encoded_location}"
            
            print(f"-> Searching: {title}")
            await page.goto(target_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000) 
            
            job_cards = await page.locator("ul.jobs-search__results-list > li").all()
            
            for card in job_cards:
                text = await card.inner_text()
                link_element = card.locator("a[href*='/jobs/view/']").first
                
                if await link_element.count() > 0:
                    href = await link_element.get_attribute("href")
                    clean_url = href.split('?')[0] if href else ""
                    
                    if text.strip() and clean_url:
                        lines = [line.strip() for line in text.split('\n') if line.strip()]
                        if len(lines) >= 2:
                            all_jobs_list.append({
                                "query_matched": title,
                                "raw_text": lines,
                                "url": clean_url,
                                "source": "LinkedIn"
                            })
        
        # Deduplicate jobs by URL
        unique_jobs = list({job['url']: job for job in all_jobs_list}.values())
        print(f"\nSuccess! Extracted {len(unique_jobs)} total LinkedIn jobs.")
        
        with open("linkedin_jobs.json", "w") as f:
            json.dump(unique_jobs, f, indent=4)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_linkedin())