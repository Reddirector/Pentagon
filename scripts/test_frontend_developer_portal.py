import sys
import time
import os
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

USER_ID = "pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd"

def run_test():
    print("=== Launching Chrome for Frontend Test 10: Master Developer Architecture Suite ===")
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
        page.wait_for_timeout(1000)

        # Set localStorage for capability token, user ID, and preferences
        page.evaluate(f"""() => {{
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
            "Conduct technical research on 2026 Microservices API Gateway and Zero-Trust Edge Security Architecture. "
            "1. Generate an interactive Single-Page Developer API Portal web application (.html) featuring responsive navigation, live interactive code tabs (cURL / Python / Node.js), and an interactive API key generator simulator. "
            "2. Generate a formal Technical Architecture & Security Specification (.docx) with structured comparison tables for rate limiting algorithms, authentication SLAs, and error codes. "
            "3. Generate an Executive Presentation deck (.pptx) with strategic roadmaps, latency benchmarks, and enterprise security milestones. "
            "4. Generate a synthetic concept image (.jpg) illustrating the Zero-Trust Edge API Gateway architecture. "
            "Synthesize everything into an authoritative executive briefing with Markdown comparison tables, GitHub-style callouts, and download cards."
        )

        textarea = page.wait_for_selector('textarea[placeholder*="Message Pentagon"]', timeout=15000)
        assert textarea, "Could not find chat input textarea"
        print("Submitting Developer Architecture Suite prompt...")
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
        overview_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_overview.png")
        page.screenshot(path=overview_path, full_page=False)
        print(f"[✓] Captured in-app overview screenshot: {overview_path}")

        # Step 2: Audit Assistant Message
        assistant_articles = page.query_selector_all('article[data-assistant-message]')
        print(f"Assistant messages rendered: {len(assistant_articles)}")
        assert len(assistant_articles) > 0, "No assistant message rendered"

        last_assistant = assistant_articles[-1]
        msg_text = last_assistant.inner_text()
        print(f"Assistant message length: {len(msg_text)} characters")

        # Step 3: Verify all file deliverable cards
        file_cards = page.query_selector_all('div.overflow-hidden.rounded-xl.border')
        print(f"Generated file deliverable cards detected: {len(file_cards)}")
        assert len(file_cards) >= 3, f"Expected at least 3 file cards, got {len(file_cards)}"

        # Step 4: Preview PPTX slide deck
        pptx_card = None
        html_card = None
        docx_card = None
        img_card = None

        for card in file_cards:
            text = card.inner_text()
            if ".pptx" in text:
                pptx_card = card
            elif ".html" in text:
                html_card = card
            elif ".docx" in text:
                docx_card = card
            elif ".jpg" in text or "image" in text.lower():
                img_card = card

        if pptx_card:
            print("Verifying PPTX slide deck preview...")
            pptx_card.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            preview_btn = pptx_card.query_selector('button:has-text("Preview")')
            if preview_btn:
                preview_btn.click()
                page.wait_for_timeout(1500)
            slide_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_slide_preview.png")
            pptx_card.screenshot(path=slide_path)
            print(f"[✓] Captured PPTX slide deck preview: {slide_path}")

        if docx_card:
            print("Verifying Docx specification preview...")
            docx_card.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            preview_btn = docx_card.query_selector('button:has-text("Preview")')
            if preview_btn:
                preview_btn.click()
                page.wait_for_timeout(1500)
            docx_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_docx_preview.png")
            docx_card.screenshot(path=docx_path)
            print(f"[✓] Captured Docx preview: {docx_path}")

        if html_card:
            print("Verifying HTML portal preview...")
            html_card.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            preview_btn = html_card.query_selector('button:has-text("Preview")')
            if preview_btn:
                preview_btn.click()
                page.wait_for_timeout(2000)
            html_path = os.path.join(ARTIFACTS_DIR, "frontend_test10_html_preview.png")
            html_card.screenshot(path=html_path)
            print(f"[✓] Captured HTML portal preview: {html_path}")

        browser.close()
        print("=== Test 10 Completed Successfully ===")

if __name__ == "__main__":
    run_test()
