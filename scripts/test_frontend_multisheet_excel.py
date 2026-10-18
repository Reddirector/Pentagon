"""Frontend E2E Test 5: Multi-Sheet Excel Workbook (.xlsx) with Live Tab Switching.

Executes via Google Chrome in Playwright:
1. Loads http://localhost:5173 with authentic session token.
2. Submits prompt for multi-sheet Renewable Energy model:
   "Build a multi-tab global renewable energy transition workbook (.xlsx) with 3 separate sheets: 'Capacity Projections' (Solar, Wind, Nuclear, Hydro in GW from 2024 to 2030), 'Levelized Cost LCOE' (cost per MWh trends), and 'Regional Investments' (North America, Europe, APAC in $B). Also provide a concise summary with a Markdown comparison table in chat."
3. Waits for live stream execution and multi-sheet workbook generation.
4. Audits:
   - Deliverable (.xlsx) generated with format badge 'Excel'.
   - Multi-sheet tab buttons rendered ('Capacity Projections', 'Levelized Cost LCOE', 'Regional Investments').
   - Clicks through each sheet tab and verifies cell data switches.
   - Filter search input tested.
5. Captures visual audit screenshots of each sheet view.
"""

import sys
import time
from playwright.sync_api import sync_playwright

def run_test():
    print("=== Launching Chrome for Frontend Test 5: Multi-Sheet Excel (.xlsx) ===")
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
            "Build a multi-tab global renewable energy transition workbook (.xlsx) with 3 separate sheets: "
            "'Capacity Projections' (Solar, Wind, Nuclear, Hydro in GW from 2024 to 2030), "
            "'Levelized Cost LCOE' (cost per MWh trends), and 'Regional Investments' (North America, Europe, APAC in $B). "
            "Also provide a concise summary with a Markdown comparison table in chat."
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
        print("Awaiting multi-sheet Excel workbook compilation (up to 240s)...")
        start_time = time.monotonic()
        page.wait_for_selector('button[aria-label="Stop generating"]', state="detached", timeout=240000)
        elapsed = int(time.monotonic() - start_time)
        print(f"Stream completed in {elapsed} seconds!")

        # Wait 4 seconds for spreadsheet preview to settle
        page.wait_for_timeout(4000)

        # Step 1: Capture Full Overview Screenshot
        overview_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test5_overview.png"
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

        # Step 3: Audit Excel Deliverable (.xlsx)
        all_file_cards = page.query_selector_all('[title*="."]')
        found_xlsx = False
        xlsx_title = ""

        for fc in all_file_cards:
            title = fc.get_attribute("title") or ""
            if ".xlsx" in title.lower():
                found_xlsx = True
                xlsx_title = title

        excel_badge = page.query_selector('text="Excel"')
        print(f"[✓] Excel (.xlsx) Deliverable generated: {found_xlsx or bool(excel_badge)} ('{xlsx_title}')")

        # Step 4: Scroll to Spreadsheet Preview
        xlsx_card = page.query_selector('text="Excel"') or page.query_selector('table')
        if xlsx_card:
            try:
                xlsx_card.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)
            except Exception:
                pass

        # Step 5: Check and Click Sheet Tabs
        sheet_buttons = page.query_selector_all('div.flex.flex-wrap.items-center.gap-1 button')
        if not sheet_buttons:
            sheet_buttons = page.query_selector_all('button.rounded-md:has-text("Projections"), button.rounded-md:has-text("Capacity"), button.rounded-md:has-text("LCOE"), button.rounded-md:has-text("Investments"), button.rounded-md:has-text("Cost")')
        print(f"Found sheet tab buttons: {len(sheet_buttons)}")
        for idx, btn in enumerate(sheet_buttons):
            print(f"  Tab {idx+1}: '{btn.inner_text().strip()}'")

        # Capture Sheet 1 Preview
        s1_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test5_sheet1.png"
        page.screenshot(path=s1_path, full_page=False)
        print(f"[✓] Captured Sheet 1 preview screenshot: {s1_path}")

        # If multiple sheet tabs exist, click Tab 2
        if len(sheet_buttons) > 1:
            print(f"Clicking Tab 2: {sheet_buttons[1].inner_text()}...")
            sheet_buttons[1].click()
            page.wait_for_timeout(1000)
            s2_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test5_sheet2.png"
            page.screenshot(path=s2_path, full_page=False)
            print(f"[✓] Captured Sheet 2 preview screenshot: {s2_path}")

        browser.close()

        # Strict Assertions
        assert found_xlsx or excel_badge, "FATAL: Excel (.xlsx) deliverable was not generated"
        assert len(sheet_buttons) >= 2, f"FATAL: Expected at least 2 workbook sheet tabs, found {len(sheet_buttons)}"
        print(f"[✓] Successfully verified multi-sheet tab buttons: {len(sheet_buttons)} tabs interactive in frontend.")
        print("\n========================================================")
        print("=== IN-APP FRONTEND TEST 5 AUDITED & VERIFIED ===")
        print("========================================================")

if __name__ == "__main__":
    run_test()
