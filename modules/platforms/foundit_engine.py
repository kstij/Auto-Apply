'''
Foundit (formerly Monster) Job Application Engine.
Automates Quick Apply job applications on Foundit with AI question answering,
persistent browser session, and unified tracking.
'''

import os
import re
import sys
import time
import random
import urllib.parse
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.platforms.base_platform import BasePlatformBot
from modules.helpers import print_lg, critical_error_log

# Import configs
import config.personals as personals
import config.questions as questions
import config.search as search
import config.secrets as secrets
import config.settings as settings

# AI Integration
ai_client = None
if getattr(secrets, "use_AI", False):
    try:
        from modules.ai.connections import create_ai_client, answer_question, close_ai_client
        ai_client = create_ai_client()
    except Exception as e:
        print_lg(f"[Foundit] AI status: {e}")


class FounditBot(BasePlatformBot):
    '''Automated Job Applier for Foundit (Monster).'''

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(platform_name="Foundit", config=config)
        self.playwright = None
        self.context = None
        self.page = None
        self.user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../userData/foundit_profile"))
        os.makedirs(self.user_data_dir, exist_ok=True)

        self.domain = getattr(secrets, "foundit_domain", "www.foundit.in") or "www.foundit.in"
        self.search_terms = getattr(search, "search_terms", ["Software Engineer"])
        self.search_location = getattr(search, "search_location", "")
        self.stop_before_submit = getattr(settings, "stop_before_submit", False)
        self.click_gap = getattr(settings, "click_gap", 2)
        self.run_in_background = getattr(settings, "run_in_background", False)

    def initialize_browser(self):
        print_lg("[Foundit] Initializing browser engine with anti-detection...")
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                import subprocess
                subprocess.run([sys.executable, "-m", "pip", "install", "playwright", "playwright-stealth"], check=True)
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                from playwright.sync_api import sync_playwright

            try:
                from playwright_stealth import stealth_sync
                has_stealth = True
            except ImportError:
                has_stealth = False

            self.playwright = sync_playwright().start()

            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox",
                "--disable-infobars"
            ]

            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.run_in_background,
                args=launch_args,
                viewport={"width": 1280, "height": 800}
            )

            if len(self.context.pages) > 0:
                self.page = self.context.pages[0]
            else:
                self.page = self.context.new_page()

            if has_stealth:
                stealth_sync(self.page)

            print_lg(f"[Foundit] Browser ready. Session profile: {self.user_data_dir}")
            return True
        except Exception as e:
            print_lg(f"[Foundit] Browser init error: {e}")
            critical_error_log("Failed to start Foundit browser", e)
            return False

    def human_delay(self, min_sec: float = 1.0, max_sec: float = 2.5):
        gap = max(self.click_gap, 1)
        time.sleep(random.uniform(min_sec * gap, max_sec * gap))

    def is_logged_in(self) -> bool:
        selectors = [
            "div.userProfile",
            "a[href*='/seeker/profile']",
            "div[data-testid='user-profile']",
            "div.user-logged-in",
            "a[href*='/dashboard']"
        ]
        for sel in selectors:
            try:
                if self.page.locator(sel).count() > 0 and self.page.locator(sel).first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def login(self) -> bool:
        print_lg(f"[Foundit] Checking session at https://{self.domain}...")
        try:
            self.page.goto(f"https://{self.domain}", wait_until="domcontentloaded", timeout=60000)
            self.human_delay(2, 3)

            if self.is_logged_in():
                print_lg("✅ [Foundit] Logged in via saved persistent session!")
                return True

            print_lg("\n=======================================================")
            print_lg("🔑 [Foundit] ONE-TIME LOGIN REQUIRED")
            print_lg("👉 Please sign in to Foundit in the open browser window.")
            print_lg("👉 The bot is waiting and will automatically proceed once logged in...")
            print_lg("=======================================================\n")

            max_wait_seconds = 180
            start_time = time.time()
            while time.time() - start_time < max_wait_seconds:
                if not self.is_running:
                    return False
                if self.is_logged_in():
                    print_lg("✅ [Foundit] Sign in detected! Session saved to profile.")
                    return True
                time.sleep(3)

            print_lg("⚠️ [Foundit] Login wait timed out. Continuing...")
            return False
        except Exception as e:
            print_lg(f"[Foundit] Login notice: {e}")
            return False

    def build_search_url(self, keyword: str, location: str) -> str:
        q = urllib.parse.quote(keyword)
        loc = urllib.parse.quote(location) if location else ""
        if loc:
            return f"https://{self.domain}/srp/results?query={q}&locations={loc}&sort=1"
        return f"https://{self.domain}/srp/results?query={q}&sort=1"

    def search_and_apply_term(self, term: str, max_apps: int = 25):
        search_url = self.build_search_url(term, self.search_location)
        print_lg(f"\n=======================================================")
        print_lg(f"🔍 [Foundit] Searching for: '{term}'")
        print_lg(f"🔗 URL: {search_url}")
        print_lg("=======================================================\n")

        try:
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            self.human_delay(3, 4)
        except Exception as e:
            print_lg(f"[Foundit] Notice loading search page: {e}")
            return

        card_selectors = "div.cardContainer, div.srpResultCard, div.jobTupleHeader"
        try:
            self.page.wait_for_selector(card_selectors, timeout=10000)
        except Exception:
            pass

        cards = self.page.locator(card_selectors).all()
        print_lg(f"[Foundit] Found {len(cards)} listings for '{term}'. Processing Quick Apply...")

        term_applied = 0
        for idx, card in enumerate(cards):
            if not self.is_running or term_applied >= max_apps:
                break

            try:
                title_el = card.locator("div.jobTitle, a.title, h3.title").first
                title = title_el.text_content().strip() if title_el.count() > 0 else f"Job #{idx+1}"

                company_el = card.locator("div.companyName, a.companyName, p.company").first
                company = company_el.text_content().strip() if company_el.count() > 0 else "Unknown Company"

                # Check blacklist
                bad_words = getattr(search, "bad_words", [])
                if any(bad and bad.lower() in title.lower() for bad in bad_words):
                    self.skipped_count += 1
                    continue

                # Locate Quick Apply / Apply button inside card
                apply_btn = card.locator("button:has-text('Quick Apply'), button:has-text('Apply'), a:has-text('Quick Apply')").first
                if apply_btn.count() == 0 or not apply_btn.is_visible():
                    card.click()
                    self.human_delay(1.5, 2.5)
                    apply_btn = self.page.locator("button:has-text('Quick Apply'), button:has-text('Apply Now')").first

                if apply_btn.count() > 0 and apply_btn.is_visible():
                    print_lg(f"\n[Foundit] 🎯 Applying: '{title}' at '{company}'")
                    apply_btn.click()
                    self.human_delay(2, 3)

                    # Check for questionnaire / submit modal
                    submit_btn = self.page.locator("button:has-text('Submit'), button:has-text('Confirm Apply'), button:has-text('Continue')").first
                    if submit_btn.count() > 0 and submit_btn.is_visible():
                        submit_btn.click()
                        self.human_delay(2, 3)

                    self.record_application(
                        job_id=f"foundit_{int(time.time())}_{idx}",
                        title=title,
                        company=company,
                        job_link=self.page.url,
                        external_link="Foundit Applied"
                    )
                    term_applied += 1
                else:
                    self.skipped_count += 1
                self.human_delay(2, 3)
            except Exception as err:
                continue

    def run(self):
        self.is_running = True
        print_lg("\n=======================================================")
        print_lg("         🟡 STARTING FOUNDIT (MONSTER) AUTO APPLIER")
        print_lg("=======================================================\n")

        if not self.initialize_browser():
            return

        self.login()
        switch_number = getattr(search, "switch_number", 25)
        for term in self.search_terms:
            if not self.is_running:
                break
            self.search_and_apply_term(term, max_apps=switch_number)
            self.human_delay(2, 4)

        print_lg(f"\n[Foundit] Completed: {self.applied_count} Applied, {self.skipped_count} Skipped, {self.failed_count} Failed.")
        self.close()

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass


if __name__ == "__main__":
    bot = FounditBot()
    bot.run()
