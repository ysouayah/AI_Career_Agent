import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def scrape_handshake():
    # We wrap Playwright in our stealth disguise again just to be safe
    async with Stealth().use_async(async_playwright()) as p:
        print("1. Launching the invisible bot...")
        browser = await p.chromium.launch(headless=True)
        
        print("2. Injecting the skeleton key (session state)...")
        # THIS is the magic line. It loads your cookies so you don't have to log in.
        context = await browser.new_context(storage_state="handshake_state.json")
        page = await context.new_page()
        
        # Tip: You can change this URL later to a specific search 
        # (e.g., searching "Data Analyst" or "Political Analyst" and copying that URL)
        target_url = "https://bu.joinhandshake.com/postings"
        
        print(f"3. Navigating directly to {target_url}...")
        # networkidle means it waits until the page has stopped loading new data
        await page.goto(target_url, wait_until="networkidle")
        
        print("4. Taking a screenshot to prove we bypassed login...")
        await page.screenshot(path="handshake_headless_proof.png", full_page=True)
        
        print("5. Grabbing the page title...")
        title = await page.title()
        print(f"Current Page Title: {title}")
        
        await browser.close()
        print("Done! Open 'handshake_headless_proof.png' to see what the bot saw.")

if __name__ == "__main__":
    asyncio.run(scrape_handshake())