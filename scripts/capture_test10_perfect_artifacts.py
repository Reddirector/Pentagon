import asyncio
import os
from playwright.async_api import async_playwright

ARTIFACTS_DIR = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3"
USER_ID = "pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd"

async def run():
    print("=== Capturing Pristine Test 10 In-Browser Artifacts in Google Chrome ===")
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

        # Select top thread in sidebar
        threads = page.locator("nav button, div[role='navigation'] button, button:has-text('Microservices'), button:has-text('Conduct')")
        if await threads.count() > 0:
            print("Clicking top conversation thread...")
            await threads.first.click()
            await page.wait_for_timeout(2500)

        # 1. Slide Deck Preview (Slide 2)
        pptx_span = page.locator("span[title*='.pptx']").first
        if await pptx_span.count() > 0:
            print("Locating PPTX card...")
            await pptx_span.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            pptx_card = pptx_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = pptx_card.locator("button:has-text('Preview')").first
            if await preview_btn.count() > 0:
                await preview_btn.click()
                await page.wait_for_timeout(1500)
            
            # Click next slide arrow to show Slide 2
            next_slide_btn = pptx_card.locator("button:has(svg.lucide-chevron-right)").first
            if await next_slide_btn.count() > 0:
                print("Advancing to Slide 2 (Architectural Vision)...")
                await next_slide_btn.click()
                await page.wait_for_timeout(1000)

            slide_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_slide_preview.png")
            await pptx_card.screenshot(path=slide_path)
            print(f"[✓] Captured Slide 2 preview: {slide_path}")

        # 2. Word Document Preview
        docx_span = page.locator("span[title*='.docx']").first
        if await docx_span.count() > 0:
            print("Locating Docx card...")
            await docx_span.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            docx_card = docx_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = docx_card.locator("button:has-text('Preview')").first
            if await preview_btn.count() > 0:
                await preview_btn.click()
                await page.wait_for_timeout(2000)

            docx_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_docx_preview.png")
            await docx_card.screenshot(path=docx_path)
            print(f"[✓] Captured Docx preview: {docx_path}")

        # 3. HTML Portal Preview
        html_span = page.locator("span[title*='.html']").first
        if await html_span.count() > 0:
            print("Locating HTML card...")
            await html_span.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)
            html_card = html_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = html_card.locator("button:has-text('Preview')").first
            if await preview_btn.count() > 0:
                await preview_btn.click()
                await page.wait_for_timeout(2000)

            html_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_html_preview.png")
            await html_card.screenshot(path=html_path)
            print(f"[✓] Captured HTML portal preview: {html_path}")

        # 4. Overview Screenshot
        overview_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_overview.png")
        await page.screenshot(path=overview_path)
        print(f"[✓] Captured full overview screenshot: {overview_path}")

        await browser.close()
        print("=== Complete! ===")

if __name__ == "__main__":
    asyncio.run(run())
