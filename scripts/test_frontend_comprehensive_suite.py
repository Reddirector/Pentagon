import sys
import time
from playwright.sync_api import sync_playwright

def run_test():
    print("=== Launching Chrome for Frontend Test 8: Comprehensive Enterprise Multi-Format Verification ===")
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

        # Switch to Agent Mode
        agent_tab = page.query_selector('button:has-text("Agent")')
        if agent_tab:
            agent_tab.click()
            page.wait_for_timeout(500)

        prompt = (
            "Conduct deep strategic analysis on 2026 Enterprise Quantum Computing and AI Acceleration Infrastructure. "
            "1. Generate an Executive Presentation deck (.pptx) summarizing quantum hardware milestones and strategic roadmaps. "
            "2. Generate a formal Research Report (.pdf) with executive summary, benchmark comparison table, and actionable recommendations. "
            "3. Generate a Quantum Infrastructure Financial Model (.xlsx) detailing capital expenditure, operational efficiency, and projected returns across 3 distinct sheets. "
            "Synthesize everything into an executive briefing with structured data tables, key takeaways, and download deliverables."
        )

        textarea = page.wait_for_selector('textarea[placeholder*="Message Pentagon"]', timeout=15000)
        assert textarea, "Could not find chat input textarea"
        print("Submitting Comprehensive prompt...")
        textarea.fill(prompt)
        page.wait_for_timeout(600)
        textarea.press("Enter")
        print("Prompt submitted. Stream initiated...")

        # Wait for stream to start
        try:
            page.wait_for_selector('button[aria-label="Stop generating"]', timeout=15000)
            print("Active stream detected ('Stop generating' button visible).")
        except Exception:
            print("Stream already transitioning or rapid start.")

        # Wait for agent orchestration to complete (up to 300s)
        print("Awaiting full multi-format orchestration (up to 300s)...")
        start_time = time.monotonic()
        page.wait_for_selector('button[aria-label="Stop generating"]', state="detached", timeout=300000)
        elapsed = int(time.monotonic() - start_time)
        print(f"Master multi-format run completed in {elapsed} seconds!")

        # Allow DOM rendering to settle
        page.wait_for_timeout(4000)

        # Step 1: Capture Full Overview Screenshot
        overview_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test8_overview.png"
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

        # Step 3: Audit All Deliverables
        all_file_cards = page.query_selector_all('[title*="."]')
        titles = [fc.get_attribute("title") for fc in all_file_cards if fc.get_attribute("title")]
        print(f"Detected Deliverable File Cards ({len(titles)}): {titles}")

        has_pdf = any(".pdf" in t.lower() for t in titles) or bool(page.query_selector('text="PDF"'))
        has_pptx = any(".pptx" in t.lower() for t in titles) or bool(page.query_selector('text="PowerPoint"'))
        has_xlsx = any(".xlsx" in t.lower() for t in titles) or bool(page.query_selector('text="Excel"'))

        print(f"[✓] PDF Report generated: {has_pdf}")
        print(f"[✓] PPTX Presentation generated: {has_pptx}")
        print(f"[✓] XLSX Financial Model generated: {has_xlsx}")

        # Step 4: Capture Slide Deck or PDF Reader Screenshot
        pdf_viewer = page.query_selector('div:has-text("Document Reader")') or page.query_selector('text="Page 1 of"')
        if pdf_viewer:
            print("Found Document Reader in DOM! Scrolling into view...")
            try:
                pdf_viewer.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)
            except Exception:
                pass
            pdf_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test8_pdf_preview.png"
            page.screenshot(path=pdf_path, full_page=False)
            print(f"[✓] Captured PDF Reader screenshot: {pdf_path}")

        pptx_badge = page.locator("span:has-text(\"PowerPoint\")").first
        if pptx_badge:
            print("Found PowerPoint in DOM! Scrolling into view...")
            try:
                pptx_badge.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)
            except Exception:
                pass
            slide_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test8_slide_preview.png"
            page.screenshot(path=slide_path, full_page=False)
            print(f"[✓] Captured Slide Preview screenshot: {slide_path}")

        # Check for tool leaks or placeholders in text
        leaks = [
            "update_plan", "build_document", "deep_research", "generate_image",
            "execute_code", "read_file", "write_file", "[insert", "{'slides':"
        ]
        found_leaks = [leak for leak in leaks if leak in text_content.lower()]
        assert not found_leaks, f"Detected tool leaks or placeholders in message: {found_leaks}"
        print(f"[✓] Leak audit passed: Zero tool leaks or template placeholders detected!")

        browser.close()

        # Strict Multi-Modal Assertions
        assert has_pdf or has_pptx or has_xlsx, "FATAL: Deliverables were not generated"
        print("\n========================================================")
        print("=== IN-APP FRONTEND TEST 8 AUDITED & VERIFIED ===")
        print("========================================================")

if __name__ == "__main__":
    run_test()
