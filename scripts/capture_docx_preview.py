import asyncio
import os
from playwright.async_api import async_playwright

ARTIFACTS_DIR = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3"
USER_ID = "pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd"

async def run():
    print("=== Capturing High-Quality Docx Preview in Chrome ===")
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

        await page.goto("http://localhost:5173")
        await page.wait_for_timeout(1000)

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

        await page.reload()
        await page.wait_for_timeout(3000)

        # Click top conversation in sidebar
        threads = page.locator("nav button, div[role='navigation'] button, button:has-text('Microservices'), button:has-text('Conduct')")
        if await threads.count() > 0:
            print("Clicking top conversation thread...")
            await threads.first.click()
            await page.wait_for_timeout(2500)

        # Find the docx card using span[title*='.docx']
        docx_span = page.locator("span[title*='.docx']").first
        await docx_span.wait_for(state="visible", timeout=10000)
        filename = await docx_span.inner_text()
        print(f"Found Docx file card: {filename}")

        await docx_span.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)

        card_container = docx_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
        preview_btn = card_container.locator("button:has-text('Preview')").first
        if await preview_btn.count() > 0:
            print("Opening Docx Preview...")
            await preview_btn.click()
            await page.wait_for_timeout(2500)

        # Wait for table in preview
        table = card_container.locator("table").first
        await table.wait_for(state="visible", timeout=10000)
        print("Found Docx table in preview!")

        # Screenshot the card container
        docx_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_docx_preview.png")
        await card_container.screenshot(path=docx_path)
        print(f"[✓] Captured high-quality Docx preview screenshot: {docx_path}")

        # Overview screenshot
        overview_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_overview.png")
        await page.screenshot(path=overview_path)
        print(f"[✓] Captured updated overview screenshot: {overview_path}")

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(run())
