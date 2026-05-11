import asyncio
from playwright.async_api import async_playwright

async def save_handshake_session():
    async with async_playwright() as p:
        print("Launching visible browser...")
        # We set headless to False so you can actually see the browser and log in
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("Navigating to Handshake...")
        await page.goto("https://app.joinhandshake.com/login")

        print("\n*** ACTION REQUIRED ***")
        print("1. Select Boston University and log in using your credentials in the browser window.")
        print("2. Complete any 2FA/Duo pushes if prompted.")
        print("3. Wait for the main Handshake dashboard to load completely.")
        print("***********************\n")

        # The script pauses here and waits for the URL to change to the student dashboard
        try:
            # We give you 2 full minutes (120,000 ms) to complete the login process
            await page.wait_for_url("**/explore**", timeout=120000) 
            print("Login detected! Saving session state...")
            
            # This is the magic line that saves your login cookies
            await context.storage_state(path="handshake_state.json")
            print("Success! Session saved to 'handshake_state.json'.")
            
        except Exception as e:
            print(f"Login timed out or failed: {e}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(save_handshake_session())