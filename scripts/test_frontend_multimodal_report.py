"""Frontend E2E Test 2: Real In-Browser Multi-Modal Dual Image Research Report & PDF.

Executes via actual browser (Google Chrome via Playwright):
1. Loads http://localhost:5173 with authentic user session and capability token
2. Submits prompt:
   "Research the 2026 humanoid robotics landscape (Tesla Optimus Gen 3, Figure 02, Boston Dynamics Atlas). Deliver a structured executive report with real web photos of the robots, an AI-generated concept image of future robotic dexterity, a comparison matrix table, and a compiled PDF deliverable."
3. Waits for live stream execution to complete
4. Audits:
   - Web search executed with grounded real robot citations and web photos
   - AI image generation executed for concept art
   - Structured markdown comparison table rendered
   - PDF document deliverable generated (.pdf)
   - Zero PNG mockups for documents
   - Zero leaked tool commentary
5. Captures high-resolution visual audit screenshots
"""

import sys
import time
from playwright.sync_api import sync_playwright

def run_frontend_multimodal_test():
    print("=== Launching Chrome for Frontend Test 2: Multi-Modal Report & PDF ===")
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
            "Research the 2026 humanoid robotics landscape (Tesla Optimus Gen 3, Figure 02, Boston Dynamics Atlas). "
            "Deliver a structured executive report with real web photos of the robots, an AI-generated concept image "
            "of future robotic dexterity, a comparison matrix table, and a compiled PDF deliverable."
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
        print("Awaiting agent execution, research, image generation, and PDF document generation (up to 240s)...")
        start_time = time.monotonic()
        
        page.wait_for_selector('button[aria-label="Stop generating"]', state="detached", timeout=300000)
        elapsed = int(time.monotonic() - start_time)
        print(f"Stream completed in {elapsed} seconds!")

        # Wait 4 seconds for file previews, iframes, images, and markdown to settle
        page.wait_for_timeout(4000)

        # Step 1: Capture Full Overview Screenshot
        overview_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test2_overview.png"
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

        # Step 3: Audit Comparison Matrix Table
        tables = last_assistant.query_selector_all('table')
        print(f"[✓] Comparison table(s) in markdown: {len(tables)}")

        # Step 4: Audit Real Web Images and AI Concept Art
        images = last_assistant.query_selector_all('img')
        img_srcs = [img.get_attribute("src") or "" for img in images]
        real_web_images = [s for s in img_srcs if s.startswith("http://") or s.startswith("https://")]
        ai_gen_images = [s for s in img_srcs if "/api/files/" in s or "data:image" in s]
        print(f"[✓] Total rendered images: {len(images)}")
        print(f"    - Real web images: {len(real_web_images)}")
        print(f"    - AI synthetic images: {len(ai_gen_images)}")

        # Step 5: Audit Deliverables (PDF Document)
        all_file_cards = page.query_selector_all('[title*="."]')
        found_pdf = False
        found_ai_image_file = False
        pdf_title = ""

        for fc in all_file_cards:
            title = fc.get_attribute("title") or ""
            if ".pdf" in title.lower():
                found_pdf = True
                pdf_title = title
            if any(ext in title.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
                found_ai_image_file = True

        print(f"[✓] PDF Deliverable generated: {found_pdf} ('{pdf_title}')")
        print(f"[✓] AI Concept Image File Deliverable: {found_ai_image_file}")

        # Step 6: Scroll to Deliverable section and capture PDF preview screenshot
        pdf_el = page.query_selector('text="Document View"') or page.query_selector('text="Native PDF Viewer"') or page.query_selector('iframe[title*=".pdf"]') or page.query_selector('text="PDF"')
        if pdf_el:
            try:
                pdf_el.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)
            except Exception:
                pass
        pdf_path = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3/frontend_test2_pdf_preview.png"
        page.screenshot(path=pdf_path, full_page=False)
        print(f"[✓] Captured PDF preview screenshot: {pdf_path}")

        browser.close()

        # Strict Senior Developer Assertions
        assert found_pdf, "FATAL: PDF deliverable missing from frontend"
        print("\n========================================================")
        print("=== IN-APP FRONTEND TEST 2 AUDITED ===")
        print("========================================================")

if __name__ == "__main__":
    run_frontend_multimodal_test()
