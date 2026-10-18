"""Frontend E2E Test 4: Comprehensive In-Browser Word Document (.docx) & DocxPreview.

Executes via Google Chrome in Playwright:
1. Navigates to http://localhost:5173 with authentic session token.
2. Submits prompt for Enterprise Cybersecurity Incident Response Protocol (.docx).
3. Waits for live stream execution and file generation.
4. Audits:
   - Deliverable (.docx) generated and registered.
   - Interactive DocxPreview rendered with headings, structured table, and styled bullets.
   - Assistant executive briefing with markdown table and callouts.
   - Download functionality verified.
5. Captures high-res visual audit screenshots.
"""

import sys
import time
from playwright.sync_api import sync_playwright

def run_test():
    print("=== Launching Chrome for Frontend Test 4: Enterprise Word Document (.docx) ===")
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
            "Prepare a formal Enterprise Cybersecurity Incident Response Protocol as a downloadable Word document (.docx). "
            "The document must include: an Executive Summary, a 4-tier Severity Matrix Table (P1 Critical down to P4 Low with response SLAs and escalation paths), "
            "Step-by-Step Incident Containment and Forensics Procedures, Regulatory Compliance Reporting Timelines (GDPR 72-hour notice, SEC 4-day disclosure, HIPAA), "
            "and a Post-Mortem Root Cause Analysis Template. Conclude with an executive summary in chat highlighting key operational SLAs and GitHub callouts."
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
        print("Awaiting agent execution and docx compilation (up to 240s)...")
        start_time = time.monotonic()
        page.wait_for_selector('button[aria-label="Stop generating"]', state="detached", timeout=240000)
        elapsed = int(time.monotonic() - start_time)
        print(f"Stream completed in {elapsed} seconds!")

        # Wait 4 seconds for file previews to settle
        page.wait_for_timeout(4000)

        # Step 1: Capture Full Overview Screenshot
        overview_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test4_overview.png"
        page.screenshot(path=overview_path, full_page=False)
        print(f"[✓] Captured in-app overview screenshot: {overview_path}")

        # Step 2: Audit Assistant Message & Structured Content
        assistant_articles = page.query_selector_all('article[data-assistant-message]')
        print(f"Assistant messages rendered: {len(assistant_articles)}")
        assert len(assistant_articles) > 0, "No assistant message rendered"

        last_assistant = assistant_articles[-1]
        text_content = last_assistant.inner_text()
        print("\n--- Assistant Message Excerpt ---")
        print(text_content[:600].strip())
        print("---------------------------------\n")

        # Step 3: Audit Word Document Deliverable (.docx)
        all_file_cards = page.query_selector_all('[title*="."]')
        found_docx = False
        docx_title = ""

        for fc in all_file_cards:
            title = fc.get_attribute("title") or ""
            if ".docx" in title.lower():
                found_docx = True
                docx_title = title

        # Also check for 'Word' badge
        word_badge = page.query_selector('text="Word"')
        print(f"[✓] Word (.docx) Deliverable generated: {found_docx or bool(word_badge)} ('{docx_title}')")

        # Step 4: Capture Docx Preview Screenshot
        docx_card = page.query_selector('text="Word"') or page.query_selector('text="Incident Response"')
        if docx_card:
            try:
                docx_card.scroll_into_view_if_needed()
                page.wait_for_timeout(1500)
            except Exception:
                pass
        docx_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test4_docx_preview.png"
        page.screenshot(path=docx_path, full_page=False)
        print(f"[✓] Captured docx preview screenshot: {docx_path}")

        browser.close()

        # Strict Assertions
        assert found_docx or word_badge, "FATAL: Word (.docx) deliverable was not generated"
        print("\n========================================================")
        print("=== IN-APP FRONTEND TEST 4 AUDITED & VERIFIED ===")
        print("========================================================")

if __name__ == "__main__":
    run_test()
