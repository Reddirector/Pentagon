import os
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = "/home/aditya/.gemini/antigravity/brain/01d6e0b7-9f1a-4aa8-afc3-d4b9742480a3"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

USER_ID = "pentagon-f861c0ab-eaee-40ed-b1ea-c5921c8cbddd"

def verify_skills():
    print("=== Launching Chrome to Verify Skills in Settings UI ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="/usr/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        page = context.new_page()

        page.goto("http://localhost:5173")
        page.wait_for_timeout(1000)

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

        page.reload()
        page.wait_for_timeout(2000)

        # Open Account/Settings menu
        print("Opening Settings dialog...")
        account_btn = page.locator("button:has-text('Aditya'), button[aria-label*='Settings'], button:has-text('Personal workspace')").first
        if account_btn.count() > 0:
            account_btn.click()
            page.wait_for_timeout(600)
            
            # Click 'Settings' in dropdown if present
            settings_opt = page.locator("button:has-text('Settings'), [role='menuitem']:has-text('Settings')").first
            if settings_opt.count() > 0:
                settings_opt.click()
                page.wait_for_timeout(1000)

        # If dialog didn't open via menu, check direct settings trigger or shortcut
        dialog = page.locator("div[role='dialog']")
        if dialog.count() == 0:
            print("Trying gear icon or settings button...")
            gear = page.locator("button[aria-label*='settings' i], button:has-text('Settings')").first
            if gear.count() > 0:
                gear.click()
                page.wait_for_timeout(1000)

        # In Settings, click "Advanced" tab
        adv_tab = page.locator("button:has-text('Advanced')").first
        if adv_tab.count() > 0:
            print("Switching to Advanced tab...")
            adv_tab.click()
            page.wait_for_timeout(1000)

        # In Advanced, click "Skills" sub-tab or scroll to Skills
        skills_sub = page.locator("button:has-text('Skills')").first
        if skills_sub.count() > 0:
            print("Clicking Skills sub-tab...")
            skills_sub.click()
            page.wait_for_timeout(1500)

        # Locate Skills section
        skills_items = page.locator("li:has(span:has-text('shipped'))")
        count = skills_items.count()
        print(f"Total skills rendered in Settings: {count}")
        
        # Print all skill names found
        names = page.locator("li span.text-small-lg").all_inner_texts()
        print("Found skill names:", names)

        # Capture screenshot of Skills Settings dialog
        screenshot_path = os.path.join(ARTIFACTS_DIR, "skills_settings_view.png")
        if dialog.count() > 0:
            dialog.screenshot(path=screenshot_path)
        else:
            page.screenshot(path=screenshot_path)
        print(f"[✓] Captured Skills Settings Screenshot: {screenshot_path}")

        browser.close()
        print("=== Skills In-Browser Verification Complete! ===")

if __name__ == "__main__":
    verify_skills()
