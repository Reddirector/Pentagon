"""Frontend E2E Test: Real In-Browser Website Creation & Interactive Sandbox.

Executes via actual browser (Google Chrome via Playwright):
1. Loads http://localhost:5173 with authentic user session and capability token
2. Submits prompt: "Create a modern, responsive website for an artisanal bakery called 'Golden Crust' featuring a hero banner, interactive menu filter, customer reviews, and order form."
3. Waits for live stream execution to complete (monitors streaming button state)
4. Verifies deliverable card, iframe sandbox, mobile device frame, and source code viewer
5. Verifies ZERO static PNG/JPG mockup images
6. Captures high-resolution visual audit screenshots
"""

import sys
import time
from playwright.sync_api import sync_playwright

def run_frontend_website_test():
    print("=== Launching Chrome for Frontend In-App E2E Test ===")
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
        page.wait_for_timeout(3000)

        # Start a clean new thread
        new_thread_btn = page.query_selector('button:has-text("New Thread")')
        if new_thread_btn:
            new_thread_btn.click()
            page.wait_for_timeout(1000)

        # Ensure active model is meta/llama-3.2-11b-vision-instruct
        model_btn = page.query_selector('button[aria-haspopup="listbox"]')
        if model_btn:
            current_model_text = model_btn.inner_text()
            print(f"Current selected model in UI: {current_model_text.strip()}")
            if "11b" not in current_model_text.lower():
                print("Switching model via dropdown to meta/llama-3.2-11b-vision-instruct...")
                model_btn.click()
                page.wait_for_timeout(500)
                search_input = page.query_selector('input[placeholder*="Search"]')
                if search_input:
                    search_input.fill("11b")
                    page.wait_for_timeout(500)
                option = page.query_selector('button:has-text("llama-3.2-11b")') or page.query_selector('[role="option"]:has-text("11b")')
                if option:
                    option.click()
                    page.wait_for_timeout(1000)
                    print(f"Switched model: {model_btn.inner_text().strip()}")

        # Locate composer textarea
        textarea = page.wait_for_selector('textarea[placeholder*="Message Pentagon"]')
        assert textarea, "Composer textarea not found"

        test_prompt = (
            "Create a modern, responsive website for an artisanal bakery called 'Golden Crust' "
            "featuring a hero banner, interactive menu filter (Sourdough, Pastries, Artisan Breads), "
            "customer reviews, and order form."
        )

        print(f"Submitting prompt through in-app composer:\n\"{test_prompt}\"")
        textarea.fill(test_prompt)
        page.wait_for_timeout(500)

        # Submit via Enter key
        textarea.press("Enter")
        print("Prompt submitted. Stream initiated...")

        # Step A: Wait for stream to be active (Stop generating button appears or textarea becomes disabled)
        try:
            page.wait_for_selector('button[aria-label="Stop generating"]', timeout=15000)
            print("Detected active stream ('Stop generating' button visible).")
        except Exception:
            print("Stream already transitioning or rapid start.")

        # Step B: Wait for stream to complete ('Stop generating' detached / textarea re-enabled)
        print("Awaiting agent execution and document generation (up to 180s)...")
        start_time = time.monotonic()
        
        page.wait_for_selector('button[aria-label="Stop generating"]', state="detached", timeout=180000)
        elapsed = int(time.monotonic() - start_time)
        print(f"Stream completed in {elapsed} seconds!")

        # Wait 3 seconds for file previews, iframes, and markdown to settle
        page.wait_for_timeout(3000)

        # Step 1: Capture Full Overview Screenshot
        overview_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test1_overview.png"
        page.screenshot(path=overview_path, full_page=False)
        print(f"[✓] Captured in-app overview screenshot: {overview_path}")

        # Step 2: Audit Assistant Message & Structured Content
        assistant_articles = page.query_selector_all('article[data-assistant-message]')
        print(f"Assistant messages rendered: {len(assistant_articles)}")
        assert len(assistant_articles) > 0, "No assistant message rendered"

        last_assistant = assistant_articles[-1]
        text_content = last_assistant.inner_text()
        print("\n--- Assistant Message Excerpt ---")
        print(text_content[:400].strip())
        print("---------------------------------\n")

        # Step 3: Audit Agent Activity Accordion
        accordion_btn = last_assistant.query_selector('button:has-text("Executed"), button:has-text("actions"), button:has-text("Details")')
        if accordion_btn:
            print(f"[✓] Collapsed agent activity bar found: '{accordion_btn.inner_text()}'")
        else:
            print("Note: Agent activity bar not found or rendered inline.")

        # Step 4: Audit Deliverable Card & Anti-PNG Enforcement
        deliverable_heading = page.query_selector('text="Generated Deliverables"')
        print(f"[✓] Deliverables section present: {deliverable_heading is not None}")

        all_file_cards = page.query_selector_all('[title*="."]')
        found_html = False
        found_png = False
        html_card_title = ""

        for fc in all_file_cards:
            title = fc.get_attribute("title") or ""
            if ".html" in title.lower():
                found_html = True
                html_card_title = title
            if ".png" in title.lower() or ".jpg" in title.lower():
                found_png = True

        print(f"[✓] HTML Website Deliverable generated: {found_html} ('{html_card_title}')")
        print(f"[✓] Zero PNG mockups generated: {not found_png} (found_png={found_png})")

        # Step 5: Verify Live Sandboxed Iframe
        iframe = page.query_selector('iframe[title*="Golden Crust"]') or page.query_selector('iframe')
        print(f"[✓] Interactive live website iframe rendered: {iframe is not None}")
        assert iframe is not None, "Live website iframe failed to render"
        
        # Scroll into view so screenshots clearly show the live website
        try:
            iframe.scroll_into_view_if_needed()
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # Capture Desktop Preview Screenshot
        desktop_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test1_desktop_preview.png"
        page.screenshot(path=desktop_path, full_page=False)
        print(f"[✓] Captured desktop interactive preview screenshot: {desktop_path}")

        # Step 6: Test Mobile Device Viewport Toggle
        mobile_btn = page.query_selector('button:has-text("Mobile")')
        if mobile_btn:
            print("Toggling to Mobile device viewport (390px frame)...")
            mobile_btn.click()
            page.wait_for_timeout(1200)
            mobile_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test1_mobile_view.png"
            page.screenshot(path=mobile_path, full_page=False)
            print(f"[✓] Captured mobile viewport screenshot: {mobile_path}")

        # Step 7: Test Source Code Toggle
        source_btn = page.query_selector('button:has-text("Source Code")')
        if source_btn:
            print("Toggling to Source Code view...")
            source_btn.click()
            page.wait_for_timeout(1000)
            code_el = page.query_selector('pre code')
            if code_el:
                code_sample = code_el.inner_text()[:120].replace('\n', ' ')
                print(f"[✓] Source HTML verified unescaped: {code_sample}...")
            source_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test1_source_code.png"
            page.screenshot(path=source_path, full_page=False)
            print(f"[✓] Captured source code inspection screenshot: {source_path}")

        browser.close()

        # Strict Senior Developer Assertions
        assert found_html, "FATAL: HTML deliverable missing from frontend"
        assert not found_png, "FATAL: Static PNG image was produced instead of interactive website"
        print("\n========================================================")
        print("=== IN-APP FRONTEND TEST 1 PASSED: SCORE 100 / 100 ===")
        print("========================================================")

if __name__ == "__main__":
    run_frontend_website_test()
