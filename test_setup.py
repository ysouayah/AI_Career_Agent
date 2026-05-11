import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def run_stealth_test():
    # Start the Playwright environment using the NEW Version 2.0 Stealth wrapper
    async with Stealth().use_async(async_playwright()) as p:
        print("1. Launching the Chromium browser...")
        # We run it headless (invisible) since that's how our final bot will run
        browser = await p.chromium.launch(headless=True)
        
        # The disguise is now applied automatically to the whole browser!
        page = await browser.new_page()
        
        print("2. Navigating to the bot detection test page...")
        await page.goto("https://bot.sannysoft.com/", wait_until="networkidle")
        
        print("3. Taking a screenshot of the results...")
        # Saves an image so we can see what the server saw
        await page.screenshot(path="stealth_results.png", full_page=True)
        
        await browser.close()
        print("Success! Open 'stealth_results.png' in your folder to see how we did.")

if __name__ == "__main__":
    asyncio.run(run_stealth_test())