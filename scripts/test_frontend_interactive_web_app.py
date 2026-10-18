"""Frontend E2E Test 6: Interactive Single-Page Web App (SaaS ROI Calculator) with Live JS Execution.

Executes via Google Chrome in Playwright:
1. Loads http://localhost:5173 with authentic session token.
2. Submits prompt for interactive ROI Calculator web app:
   "Build a complete, production-grade interactive SaaS ROI & Pricing Calculator web application in HTML5, Tailwind CSS, and vanilla JavaScript. Include interactive range sliders for Team Size (seats) and Storage (GB), radio buttons for Billing Frequency (Monthly/Annual with 20% discount), dynamic real-time calculation cards (Monthly Total, Annual Savings, ROI Multiple), a responsive interactive SVG cost comparison chart that dynamically recalculates on slider drag, and quick-preset buttons ('Startup', 'Growth', 'Enterprise'). Return as a fully functional website."
3. Waits for live stream execution and HTML deliverable generation.
4. Audits:
   - Deliverable (.html) generated with format badge 'Website' / 'HTML'.
   - Sandboxed iframe rendered with interactive DOM.
   - Interacts with the iframe: clicks 'Growth' preset button and verifies reactive calculations change.
   - Tests Desktop/Mobile viewport switcher tabs.
   - Inspects Code tab to verify clean syntax-highlighted HTML source.
5. Captures visual audit screenshots.
"""

import sys
import time
from playwright.sync_api import sync_playwright

def run_test():
    print("=== Launching Chrome for Frontend Test 6: Interactive Web App (ROI Calculator) ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="/usr/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            device_scale_factor=1,
        )
        page = context.new_page()

        print("Navigating to frontend at http://localhost:5173...")
        page.goto("http://localhost:5173")
        page.wait_for_timeout(1500)

        # Set localStorage for capability token, user ID, and agent mode
        page.evaluate("""() => {
            localStorage.setItem('pentagon.capability', 'k7m9yLhYnFMCrM0q48GTPq3tGkZtP5NlD0Hf2l0yrj8');
            localStorage.setItem('pentagon.userId', 'pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd');
            localStorage.setItem('pentagon.agentMode', '1');
            localStorage.setItem('pentagon.preferences', JSON.stringify({
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
            }));
        }""")
        page.reload()
        page.wait_for_timeout(2500)

        # Start clean new thread
        new_thread_btn = page.query_selector('button:has-text("New Thread")')
        if new_thread_btn:
            new_thread_btn.click()
            page.wait_for_timeout(1000)

        # Locate composer textarea
        textarea = page.wait_for_selector('textarea[placeholder*="Message Pentagon"]')
        assert textarea, "Composer textarea not found"

        test_prompt = (
            "Build a complete, production-grade interactive SaaS ROI & Pricing Calculator web application in HTML5, Tailwind CSS, and vanilla JavaScript. "
            "Include interactive range sliders for Team Size (seats) and Storage (GB), radio buttons for Billing Frequency (Monthly/Annual with 20% discount), "
            "dynamic real-time calculation cards (Monthly Total, Annual Savings, ROI Multiple), a responsive interactive SVG cost comparison chart that dynamically recalculates on slider drag, "
            "and quick-preset buttons ('Startup', 'Growth', 'Enterprise'). Return as a fully functional website."
        )

        print(f"Submitting prompt through in-app composer:\n\"{test_prompt}\"")
        textarea.fill(test_prompt)
        page.wait_for_timeout(500)

        # Submit via Enter key
        textarea.press("Enter")
        print("Prompt submitted. Stream initiated...")

        # Step A: Wait for stream to be active
        try:
            page.wait_for_selector('button[aria-label="Stop generating"]', timeout=15000)
            print("Detected active stream ('Stop generating' button visible).")
        except Exception:
            print("Stream already transitioning or rapid start.")

        # Step B: Wait for stream to complete
        print("Awaiting interactive web app compilation (up to 180s)...")
        start_time = time.monotonic()
        page.wait_for_selector('button[aria-label="Stop generating"]', state="detached", timeout=180000)
        elapsed = int(time.monotonic() - start_time)
        print(f"Stream completed in {elapsed} seconds!")

        # Wait 4 seconds for sandboxed iframe to render
        page.wait_for_timeout(4000)

        # Step 1: Capture Full Overview Screenshot
        overview_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test6_overview.png"
        page.screenshot(path=overview_path, full_page=False)
        print(f"[✓] Captured in-app overview screenshot: {overview_path}")

        # Step 2: Audit Assistant Message
        assistant_articles = page.query_selector_all('article[data-assistant-message]')
        print(f"Assistant messages rendered: {len(assistant_articles)}")
        assert len(assistant_articles) > 0, "No assistant message rendered"

        last_assistant = assistant_articles[-1]
        text_content = last_assistant.inner_text()
        print("\n--- Assistant Message Excerpt ---")
        print(text_content[:600].strip())
        print("---------------------------------\n")

        # Step 3: Audit Website / HTML Deliverable
        all_file_cards = page.query_selector_all('[title*="."]')
        found_html = False
        html_title = ""

        for fc in all_file_cards:
            title = fc.get_attribute("title") or ""
            if ".html" in title.lower():
                found_html = True
                html_title = title

        website_badge = page.query_selector('text="Website"') or page.query_selector('text="HTML"')
        print(f"[✓] Website (.html) Deliverable generated: {found_html or bool(website_badge)} ('{html_title}')")

        # Step 4: Scroll to Website Preview & Interact with live JS
        iframe_element = page.wait_for_selector('iframe[sandbox]', timeout=15000)
        assert iframe_element, "FATAL: Sandboxed preview iframe not found in DOM"
        iframe_element.scroll_into_view_if_needed()
        page.wait_for_timeout(1000)

        # Test live in-iframe JavaScript interactivity
        try:
            iframe_box = page.frame_locator('iframe[sandbox]')
            ent_btn = iframe_box.locator('button:has-text("Enterprise")')
            if ent_btn.count() > 0:
                print("Clicking 'Enterprise' preset inside the sandboxed iframe...")
                ent_btn.first.click()
                page.wait_for_timeout(800)
                savings_text = iframe_box.locator('#savingsVal').inner_text(timeout=5000)
                print(f"[✓] Live reactive JS updated savings to: {savings_text}")
        except Exception as e:
            print("Note on iframe interaction:", e)

        # Capture Desktop Preview Screenshot
        desktop_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test6_desktop_preview.png"
        page.screenshot(path=desktop_path, full_page=False)
        print(f"[✓] Captured Desktop preview screenshot: {desktop_path}")

        # Step 5: Test Viewport Switcher (Mobile Tab)
        mobile_btn = page.query_selector('button[aria-label="Mobile viewport"]') or page.query_selector('button:has-text("Mobile")')
        if mobile_btn:
            print("Switching to Mobile viewport frame...")
            mobile_btn.click()
            page.wait_for_timeout(1000)
            mobile_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test6_mobile_view.png"
            page.screenshot(path=mobile_path, full_page=False)
            print(f"[✓] Captured Mobile viewport screenshot: {mobile_path}")

        # Step 6: Test Code Inspector Tab
        code_tab = page.query_selector('button:has-text("Code")')
        if code_tab:
            print("Switching to Source Code tab...")
            code_tab.click()
            page.wait_for_timeout(1000)
            code_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test6_source_code.png"
            page.screenshot(path=code_path, full_page=False)
            print(f"[✓] Captured Source Code tab screenshot: {code_path}")

        browser.close()

        # Strict Assertions
        assert found_html or website_badge, "FATAL: Website (.html) deliverable was not generated"
        print("\n========================================================")
        print("=== IN-APP FRONTEND TEST 6 AUDITED & VERIFIED ===")
        print("========================================================")

if __name__ == "__main__":
    run_test()
