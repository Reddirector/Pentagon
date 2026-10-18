import sys
import time
import os
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

USER_ID = "pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd"

def run_test():
    print("=== Launching Google Chrome for Frontend Test 11: Autonomous EV Fleet Telemetry & Safety Suite ===")
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
            print("Starting clean New Thread...")
            new_thread_btn.click()
            page.wait_for_timeout(1200)

        # Ensure Agent Mode is selected
        agent_tab = page.query_selector('button:has-text("Agent")')
        if agent_tab:
            agent_tab.click()
            page.wait_for_timeout(500)

        prompt = (
            "Conduct a rigorous engineering audit and operational financial forecast for our 2026 Autonomous Electric Vehicle Fleet Safety & Energy Telemetry Platform. "
            "1. Deliver an interactive Web Application Portal (.html) titled '2026 Autonomous EV Fleet Safety & Telemetry Operations Portal' featuring responsive telemetry graphs, battery thermal status controls, and speed/efficiency sliders. "
            "2. Deliver a multi-page regulatory audit report (.pdf) titled '2026 Autonomous EV Fleet ISO 26262 ASIL-D Functional Safety Audit Report' detailing ISO 26262 functional safety, ASIL-D fault mitigation metrics, and sensor fusion redundancy protocols. "
            "3. Deliver a multi-sheet operational and financial model (.xlsx) titled '2026 Autonomous EV Fleet Telemetry & Financial Model' with 3 distinct sheets: 'Telemetry & Battery Health', 'Degradation & Maintenance', and 'TCO & Energy Cost Analysis'. "
            "4. Deliver an executive slide deck (.pptx) titled '2026 Autonomous EV Fleet Strategic & Safety Executive Deck' with 4 structured slides summarizing fleet milestones, ASIL-D safety validation, cost per passenger mile, and 2026 deployment roadmap. "
            "5. Deliver an AI system concept illustration (.jpg) titled 'Autonomous EV Fleet Telemetry & Sensor Fusion Platform Diagram'. "
            "Synthesize everything with executive insights, comparative metrics, and clear download cards."
        )

        textarea = page.wait_for_selector('textarea[placeholder*="Message Pentagon"]', timeout=15000)
        assert textarea, "Could not find chat input textarea"
        print("Submitting Autonomous EV Fleet Suite prompt...")
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

        # Overview screenshot
        overview_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_overview.png")
        page.screenshot(path=overview_path, full_page=False)
        print(f"[✓] Captured Full Overview: {overview_path}")

        # Check all cards
        file_cards = page.locator("div.overflow-hidden.rounded-xl.border:has(span[title*='.'])")
        card_count = file_cards.count()
        print(f"Detected {card_count} generated deliverable cards in chat.")

        # 1. Preview HTML Web App Portal
        html_span = page.locator("span[title*='.html']").first
        if html_span.count() > 0:
            print("Locating HTML Web App card...")
            html_span.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            html_card = html_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = html_card.locator("button:has-text('Preview')").first
            if preview_btn.count() > 0:
                preview_btn.click()
                page.wait_for_timeout(2500)
            html_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_html_preview.png")
            html_card.screenshot(path=html_path)
            print(f"[✓] Captured HTML Portal preview: {html_path}")

        # 2. Preview PDF Report
        pdf_span = page.locator("span[title*='.pdf']").first
        if pdf_span.count() > 0:
            print("Locating PDF Report card...")
            pdf_span.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            pdf_card = pdf_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = pdf_card.locator("button:has-text('Preview')").first
            if preview_btn.count() > 0:
                preview_btn.click()
                page.wait_for_timeout(2500)
            pdf_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_pdf_preview.png")
            pdf_card.screenshot(path=pdf_path)
            print(f"[✓] Captured PDF Report preview: {pdf_path}")

        # 3. Preview Excel Multi-Sheet Workbook
        xlsx_span = page.locator("span[title*='.xlsx']").first
        if xlsx_span.count() > 0:
            print("Locating Excel Workbook card...")
            xlsx_span.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            xlsx_card = xlsx_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = xlsx_card.locator("button:has-text('Preview')").first
            if preview_btn.count() > 0:
                preview_btn.click()
                page.wait_for_timeout(2500)
            
            # Sheet 1
            s1_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_sheet1.png")
            xlsx_card.screenshot(path=s1_path)
            print(f"[✓] Captured Excel Sheet 1 preview: {s1_path}")

            # Check sheet buttons
            sheet_buttons = xlsx_card.locator("div.flex.flex-wrap.items-center.gap-1 button")
            btn_count = sheet_buttons.count()
            print(f"Found {btn_count} Excel sheet tabs.")
            if btn_count >= 2:
                print("Switching to Sheet 2...")
                sheet_buttons.nth(1).click()
                page.wait_for_timeout(1000)
                s2_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_sheet2.png")
                xlsx_card.screenshot(path=s2_path)
                print(f"[✓] Captured Excel Sheet 2 preview: {s2_path}")

            if btn_count >= 3:
                print("Switching to Sheet 3...")
                sheet_buttons.nth(2).click()
                page.wait_for_timeout(1000)
                s3_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_sheet3.png")
                xlsx_card.screenshot(path=s3_path)
                print(f"[✓] Captured Excel Sheet 3 preview: {s3_path}")

            # Test cell filtering
            filter_input = xlsx_card.locator("input[placeholder='Filter cells...']").first
            if filter_input.count() > 0:
                print("Testing Excel live cell search filter...")
                filter_input.fill("2026")
                page.wait_for_timeout(800)
                filtered_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_sheet_filtered.png")
                xlsx_card.screenshot(path=filtered_path)
                print(f"[✓] Captured filtered Excel preview: {filtered_path}")

        # 4. Preview PPTX Slide Deck
        pptx_span = page.locator("span[title*='.pptx']").first
        if pptx_span.count() > 0:
            print("Locating PPTX card...")
            pptx_span.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            pptx_card = pptx_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = pptx_card.locator("button:has-text('Preview')").first
            if preview_btn.count() > 0:
                preview_btn.click()
                page.wait_for_timeout(2000)

            # Advance to Slide 2
            next_slide_btn = pptx_card.locator("button:has(svg.lucide-chevron-right)").first
            if next_slide_btn.count() > 0:
                print("Advancing to Slide 2...")
                next_slide_btn.click()
                page.wait_for_timeout(1000)

            slide_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_slide2.png")
            pptx_card.screenshot(path=slide_path)
            print(f"[✓] Captured PPTX Slide 2 preview: {slide_path}")

        # 5. Preview Image Card
        img_span = page.locator("span[title*='.jpg'], span[title*='.png']").first
        if img_span.count() > 0:
            print("Locating Concept Image card...")
            img_span.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            img_card = img_span.locator("xpath=ancestor::div[contains(@class, 'rounded-xl')][1]")
            preview_btn = img_card.locator("button:has-text('Preview')").first
            if preview_btn.count() > 0:
                preview_btn.click()
                page.wait_for_timeout(1500)
            img_path = os.path.join(ARTIFACTS_DIR, "frontend_test11_image.png")
            img_card.screenshot(path=img_path)
            print(f"[✓] Captured Concept Image preview: {img_path}")

        browser.close()
        print("=== Test 11 Finished Successfully! ===")

if __name__ == "__main__":
    run_test()
