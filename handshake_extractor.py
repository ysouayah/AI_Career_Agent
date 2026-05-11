import asyncio
import json
import urllib.parse
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def extract_job_data():
    # 1. Load the AI's target queries
    try:
        with open("target_queries.json", "r") as f:
            queries = json.load(f)
    except FileNotFoundError:
        print("Error: target_queries.json not found. Run brainstormer.py first.")
        return

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state="handshake_state.json")
        page = await context.new_page()
        
        all_jobs_list = []
        
        print(f"Loaded {len(queries)} target queries. Starting Handshake scrape...")

        # 2. Loop through every job title
        for query in queries:
            encoded_query = urllib.parse.quote(query)
            target_url = f"https://bu.joinhandshake.com/job-search?query={encoded_query}"
            
            print(f"-> Searching: {query}")
            await page.goto(target_url, wait_until="networkidle")
            await page.wait_for_timeout(5000) 
            
            job_elements = await page.locator("a[href*='/jobs/']").all()
            
            for element in job_elements:
                text = await element.inner_text()
                href = await element.get_attribute("href")
                
                if text.strip() and href:
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    if len(lines) >= 2:
                        full_link = f"https://bu.joinhandshake.com{href}"
                        all_jobs_list.append({
                            "query_matched": query,
                            "raw_text": lines,
                            "url": full_link,
                            "source": "Handshake"
                        })
        
        unique_jobs = list({job['url']: job for job in all_jobs_list}.values())
        print(f"\nSuccess! Extracted {len(unique_jobs)} total Handshake jobs.")
        
        with open("handshake_jobs.json", "w") as f:
            json.dump(unique_jobs, f, indent=4)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(extract_job_data())