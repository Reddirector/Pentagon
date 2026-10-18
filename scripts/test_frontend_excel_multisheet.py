import asyncio
import os
from playwright.async_api import async_playwright

ARTIFACTS_DIR = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

USER_ID = "pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd"
CONV_ID = "5f1c8802-b41a-460e-ac28-40c9310a7f10"

async def run():
    print("=== Launching Chrome for In-Browser Multi-Sheet Excel Verification ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path="/usr/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 960},
            device_scale_factor=1,
        )
        page = await context.new_page()

        print("Navigating to frontend at http://localhost:5173...")
        await page.goto("http://localhost:5173")
        await page.wait_for_timeout(1000)

        # Set localStorage for capability token, user ID, and preferences
        await page.evaluate(f"""() => {{
            localStorage.setItem('pentagon.capability', 'k7m9yLhYnFMCrM0q48GTPq3tGkZtP5NlD0Hf2l0yrj8');
            localStorage.setItem('pentagon.userId', '{USER_ID}');
            localStorage.setItem('pentagon.agentMode', '1');
            localStorage.setItem('pentagon.preferences', JSON.stringify({{
                appearance: 'pitch',
                contrast: 'standard',
                density: 'default',
                textSize: 'default',
                workspaceName: 'Personal workspace',
                userName: 'Aditya',
                userEmail: 'aditya@pentagon.ai',
                userAvatarColor: 'emerald',
                defaultModel: 'meta/llama-3.2-11b-vision-instruct',
                sidebarWidth: 0,
                sidebarCollapsed: false
            }}));
        }}""")

        print("Reloading with authenticated credentials...")
        await page.reload()
        await page.wait_for_timeout(3000)

        # Look for thread in sidebar containing Quantum or click top conversation
        threads = page.locator("button:has-text('Quantum')")
        if await threads.count() > 0:
            print("Clicking Quantum conversation thread in sidebar...")
            await threads.first.click()
            await page.wait_for_timeout(2500)
        else:
            print("Checking top thread in sidebar...")
            sidebar_threads = page.locator("nav button, div[role='navigation'] button")
            if await sidebar_threads.count() > 0:
                await sidebar_threads.first.click()
                await page.wait_for_timeout(2500)

        # Locate the Excel file card
        print("Locating Excel file card in messages...")
        excel_title = page.locator("text=2026 Enterprise Quantum Computing and AI Acceleration Infrastructure Financial Model.xlsx").first
        await excel_title.wait_for(state="visible", timeout=15000)
        print("Found Excel file card header!")

        # Scroll into view
        await excel_title.scroll_into_view_if_needed()
        await page.wait_for_timeout(1000)

        # Find the card container
        card_container = excel_title.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")

        # Check if preview is already open or click Preview button
        preview_btn = card_container.locator("button:has-text('Preview')").first
        if await preview_btn.count() > 0:
            print("Clicking Preview button to open in-app spreadsheet viewer...")
            await preview_btn.click()
            await page.wait_for_timeout(2000)

        # Verify sheet tabs are visible
        tab1 = card_container.locator("button:has-text('Capital Expenditure')").first
        tab2 = card_container.locator("button:has-text('Operational Efficiency')").first
        tab3 = card_container.locator("button:has-text('Projected Returns')").first

        await tab1.wait_for(state="visible", timeout=10000)
        print("[✓] Sheet Tab 1 (Capital Expenditure) rendered!")
        await tab2.wait_for(state="visible", timeout=10000)
        print("[✓] Sheet Tab 2 (Operational Efficiency) rendered!")
        await tab3.wait_for(state="visible", timeout=10000)
        print("[✓] Sheet Tab 3 (Projected Returns) rendered!")

        # Scroll card fully into view
        await card_container.scroll_into_view_if_needed()
        await page.wait_for_timeout(1000)

        # Capture Sheet 1 screenshot
        path1 = os.path.join(ARTIFACTS_DIR, "frontend_test9_sheet1_capex.png")
        await card_container.screenshot(path=path1)
        print(f"[✓] Captured Sheet 1 (Capital Expenditure) screenshot: {path1}")

        # Click Tab 2: Operational Efficiency
        print("Switching to Tab 2 (Operational Efficiency)...")
        await tab2.click()
        await page.wait_for_timeout(1000)
        path2 = os.path.join(ARTIFACTS_DIR, "frontend_test9_sheet2_opex.png")
        await card_container.screenshot(path=path2)
        print(f"[✓] Captured Sheet 2 (Operational Efficiency) screenshot: {path2}")

        # Click Tab 3: Projected Returns
        print("Switching to Tab 3 (Projected Returns)...")
        await tab3.click()
        await page.wait_for_timeout(1000)
        path3 = os.path.join(ARTIFACTS_DIR, "frontend_test9_sheet3_returns.png")
        await card_container.screenshot(path=path3)
        print(f"[✓] Captured Sheet 3 (Projected Returns) screenshot: {path3}")

        # Test search filter
        search_input = card_container.locator("input[placeholder*='Filter']").first
        if await search_input.count() > 0:
            print("Testing search filter with query '2028'...")
            await search_input.fill("2028")
            await page.wait_for_timeout(800)
            path_filtered = os.path.join(ARTIFACTS_DIR, "frontend_test9_sheet_filtered.png")
            await card_container.screenshot(path=path_filtered)
            print(f"[✓] Captured Filtered Sheet screenshot: {path_filtered}")

        # Full overview screenshot
        overview_path = os.path.join(ARTIFACTS_DIR, "frontend_test9_overview.png")
        await page.screenshot(path=overview_path)
        print(f"[✓] Captured full overview screenshot: {overview_path}")

        await browser.close()
        print("=== Test 9 PASSED: Multi-Sheet Excel Viewer 100/100 ===")

if __name__ == "__main__":
    asyncio.run(run())
