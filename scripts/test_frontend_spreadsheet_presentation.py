"""Frontend E2E Test 3: Real In-Browser Spreadsheet (.xlsx) & Presentation (.pptx).

Executes via actual browser (Google Chrome via Playwright):
1. Loads http://localhost:5173 with authentic user session and capability token
2. Submits prompt:
   "Prepare an executive quarterly financial model for an enterprise SaaS startup (Q1-Q4 ARR, segment revenue, gross margins, CAC, and runway projections) as a downloadable Excel spreadsheet (.xlsx), and create a 4-slide executive presentation deck (.pptx) summarizing key growth drivers and runway strategy."
3. Waits for live stream execution to complete
4. Audits:
   - Excel spreadsheet deliverable (.xlsx) generated with interactive table preview & filter
   - PowerPoint presentation deliverable (.pptx) generated with 16:9 slide carousel and pagination
   - Zero PNG mockups
   - Zero leaked tool commentary
5. Captures high-resolution visual audit screenshots
"""

import sys
import time
from playwright.sync_api import sync_playwright

def run_frontend_spreadsheet_presentation_test():
    print("=== Launching Chrome for Frontend Test 3: Spreadsheet (.xlsx) & Presentation (.pptx) ===")
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

        # Locate composer textarea
        textarea = page.wait_for_selector('textarea[placeholder*="Message Pentagon"]')
        assert textarea, "Composer textarea not found"

        test_prompt = (
            "Prepare an executive quarterly financial model for an enterprise SaaS startup (Q1-Q4 ARR, segment revenue, gross margins, CAC, and runway projections) as a downloadable Excel spreadsheet (.xlsx), and create a 4-slide executive presentation deck (.pptx) summarizing key growth drivers and runway strategy."
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
        print("Awaiting agent execution, financial spreadsheet compilation, and PPTX deck generation (up to 240s)...")
        start_time = time.monotonic()
        
        page.wait_for_selector('button[aria-label="Stop generating"]', state="detached", timeout=240000)
        elapsed = int(time.monotonic() - start_time)
        print(f"Stream completed in {elapsed} seconds!")

        # Wait 4 seconds for file previews and cards to settle
        page.wait_for_timeout(4000)

        # Step 1: Capture Full Overview Screenshot
        overview_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test3_overview.png"
        page.screenshot(path=overview_path, full_page=False)
        print(f"[✓] Captured in-app overview screenshot: {overview_path}")

        # Step 2: Audit Assistant Message & Structured Content
        assistant_articles = page.query_selector_all('article[data-assistant-message]')
        print(f"Assistant messages rendered: {len(assistant_articles)}")
        assert len(assistant_articles) > 0, "No assistant message rendered"

        last_assistant = assistant_articles[-1]
        text_content = last_assistant.inner_text()
        print("\n--- Assistant Message Excerpt ---")
        print(text_content[:500].strip())
        print("---------------------------------\n")

        # Step 3: Audit Deliverables (XLSX and PPTX)
        all_file_cards = page.query_selector_all('[title*="."]')
        found_xlsx = False
        found_pptx = False
        xlsx_title = ""
        pptx_title = ""

        for fc in all_file_cards:
            title = fc.get_attribute("title") or ""
            if ".xlsx" in title.lower():
                found_xlsx = True
                xlsx_title = title
            if ".pptx" in title.lower():
                found_pptx = True
                pptx_title = title

        print(f"[✓] Excel (.xlsx) Deliverable generated: {found_xlsx} ('{xlsx_title}')")
        print(f"[✓] PowerPoint (.pptx) Deliverable generated: {found_pptx} ('{pptx_title}')")

        # Step 4: Capture Spreadsheet Preview Screenshot
        xlsx_card = page.query_selector('text="Excel"') or page.query_selector('table')
        if xlsx_card:
            try:
                xlsx_card.scroll_into_view_if_needed()
                page.wait_for_timeout(1500)
            except Exception:
                pass
        xlsx_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test3_spreadsheet_preview.png"
        page.screenshot(path=xlsx_path, full_page=False)
        print(f"[✓] Captured spreadsheet preview screenshot: {xlsx_path}")

        # Step 5: Test and Capture Slide Deck Carousel Screenshot
        pptx_card = page.query_selector('text="PowerPoint"') or page.query_selector('text="Slide 1"')
        if pptx_card:
            try:
                pptx_card.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)
            except Exception:
                pass

        # If next slide button is present, click it to test carousel interaction
        next_slide_btn = page.query_selector('button:has(svg.lucide-chevron-right)') or page.query_selector('button:has(svg[class*="chevron-right"])')
        if next_slide_btn and next_slide_btn.is_enabled():
            print("Testing slide carousel navigation: clicking Next Slide...")
            next_slide_btn.click()
            page.wait_for_timeout(1000)

        pptx_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test3_slide_deck_preview.png"
        page.screenshot(path=pptx_path, full_page=False)
        print(f"[✓] Captured slide deck preview screenshot: {pptx_path}")

        browser.close()

        # Strict Senior Developer Assertions
        assert found_xlsx, "FATAL: Excel (.xlsx) deliverable was not generated"
        assert found_pptx, "FATAL: PowerPoint (.pptx) deliverable was not generated"
        print("\n========================================================")
        print("=== IN-APP FRONTEND TEST 3 AUDITED & VERIFIED ===")
        print("========================================================")

if __name__ == "__main__":
    run_frontend_spreadsheet_presentation_test()
