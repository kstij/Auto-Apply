'''
Glassdoor Job Application Engine.
Integrates Glassdoor Easy Apply automation with AI question-answering,
persistent browser sessions, and unified application tracking.
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
        print_lg(f"[Glassdoor] Note: AI client status: {e}")


class GlassdoorBot(BasePlatformBot):
    '''Automated Job Applier for Glassdoor featuring Easy Apply and AI form answering.'''

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(platform_name="Glassdoor", config=config)
        self.playwright = None
        self.context = None
        self.page = None
        self.user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../userData/glassdoor_profile"))
        os.makedirs(self.user_data_dir, exist_ok=True)

        self.search_terms = getattr(search, "search_terms", ["Software Engineer"])
        self.search_location = getattr(search, "search_location", "")
        self.stop_before_submit = getattr(settings, "stop_before_submit", False)
        self.click_gap = getattr(settings, "click_gap", 2)
        self.run_in_background = getattr(settings, "run_in_background", False)

    def initialize_browser(self):
        '''Initialize Playwright browser with persistent context and stealth.'''
        print_lg("[Glassdoor] Initializing browser engine with anti-detection...")
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                print_lg("[Glassdoor] Installing Playwright and Chromium automatically...")
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
                "--disable-infobars",
                "--disable-dev-shm-usage"
            ]

            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.run_in_background,
                args=launch_args,
                viewport={"width": 1280, "height": 800},
                locale="en-US"
            )

            if len(self.context.pages) > 0:
                self.page = self.context.pages[0]
            else:
                self.page = self.context.new_page()

            if has_stealth:
                stealth_sync(self.page)

            print_lg(f"[Glassdoor] Browser ready. Session profile: {self.user_data_dir}")
            return True
        except Exception as e:
            print_lg(f"[Glassdoor] Browser init error: {e}")
            critical_error_log("Failed to start Glassdoor browser", e)
            return False

    def human_delay(self, min_sec: float = 1.0, max_sec: float = 2.5):
        gap = max(self.click_gap, 1)
        time.sleep(random.uniform(min_sec * gap, max_sec * gap))

    def is_logged_in(self) -> bool:
        '''Check if authenticated on Glassdoor.'''
        profile_selectors = [
            "button[data-test='profile-icon']",
            "button[data-test='user-menu-button']",
            "div[data-test='avatar']",
            "a[href*='/member/home']",
            "a[href*='/profile']"
        ]
        for sel in profile_selectors:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return True
            except Exception:
                continue
        url = self.page.url.lower()
        if "glassdoor.com" in url and not any(p in url for p in ["/login", "/member/login", "/auth"]):
            signin_loc = self.page.locator("button:has-text('Sign In'), a:has-text('Sign In'), a[href*='/login']")
            if signin_loc.count() == 0:
                return True
        return False

    def login(self) -> bool:
        '''Check login status or prompt one-time Google/Email sign-in.'''
        print_lg("[Glassdoor] Checking session state at https://www.glassdoor.com...")
        try:
            self.page.goto("https://www.glassdoor.com/Job/jobs.htm", wait_until="domcontentloaded", timeout=60000)
            self.human_delay(2, 3)

            if self.is_logged_in():
                print_lg("✅ [Glassdoor] Logged in via saved persistent session!")
                return True

            print_lg("\n=======================================================")
            print_lg("🔑 [Glassdoor] ONE-TIME LOGIN REQUIRED")
            print_lg("👉 Please sign in to Glassdoor in the open browser window.")
            print_lg("👉 The bot is waiting and will automatically proceed once logged in...")
            print_lg("=======================================================\n")

            # Wait loop for user to sign in
            max_wait_seconds = 180
            start_time = time.time()
            notified_halfway = False

            while time.time() - start_time < max_wait_seconds:
                if not self.is_running:
                    return False
                if self.is_logged_in():
                    print_lg("✅ [Glassdoor] Sign in detected! Session saved to profile.")
                    self.human_delay(2, 3)
                    return True

                elapsed = int(time.time() - start_time)
                if elapsed > 30 and not notified_halfway:
                    print_lg(f"[Glassdoor] Still waiting for sign in... ({max_wait_seconds - elapsed}s remaining).")
                    notified_halfway = True
                time.sleep(3)

            print_lg("⚠️ [Glassdoor] Login wait timed out. Proceeding...")
            return False
        except Exception as e:
            print_lg(f"[Glassdoor] Login notice: {e}")
            return False

    def build_search_url(self, keyword: str, location: str) -> str:
        params = {"keyword": keyword}
        if location:
            params["locKeyword"] = location
        query_str = urllib.parse.urlencode(params)
        return f"https://www.glassdoor.com/Job/jobs.htm?{query_str}&fromAge=7&filter.jobType=all"

    def search_and_apply_term(self, term: str, max_apps: int = 25):
        '''Search for a keyword on Glassdoor and apply to Easy Apply jobs.'''
        search_url = self.build_search_url(term, self.search_location)
        print_lg(f"\n=======================================================")
        print_lg(f"🔍 [Glassdoor] Searching for: '{term}' in '{self.search_location or 'Anywhere'}'")
        print_lg(f"🔗 URL: {search_url}")
        print_lg("=======================================================\n")

        try:
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            self.human_delay(3, 4)
        except Exception as e:
            print_lg(f"[Glassdoor] Search page notice: {e}")
            return

        card_selectors = "li[data-test='jobListing'], div[data-test='job-listing'], div.JobsList_jobListItem__JBBU2"
        try:
            self.page.wait_for_selector(card_selectors, timeout=10000)
        except Exception:
            pass

        cards = self.page.locator(card_selectors).all()
        print_lg(f"[Glassdoor] Found {len(cards)} listings for '{term}'. Processing Easy Apply...")

        term_applied = 0
        for idx, card in enumerate(cards):
            if not self.is_running or term_applied >= max_apps:
                break

            try:
                title_el = card.locator("a[data-test='job-title'], a.JobCard_jobTitle___P9L7").first
                title = title_el.text_content().strip() if title_el.count() > 0 else f"Job #{idx+1}"

                company_el = card.locator("span[data-test='employer-name'], span.EmployerProfile_compactEmployerName__9MGcV").first
                company = company_el.text_content().strip() if company_el.count() > 0 else "Unknown Company"

                # Check Easy Apply indicator
                has_easy_apply = card.locator("span:has-text('Easy Apply'), [data-test='easy-apply-badge']").count() > 0

                # Click on the job card
                card.click()
                self.human_delay(1.5, 2.5)

                job_data = {
                    "id": f"gd_{int(time.time())}_{idx}",
                    "title": title,
                    "company": company,
                    "link": self.page.url,
                    "is_easy_apply": has_easy_apply
                }

                applied = self.apply_to_job(job_data)
                if applied:
                    term_applied += 1
                self.human_delay(2, 3)
            except Exception as err:
                continue

    def apply_to_job(self, job_data: Dict[str, Any]) -> bool:
        title = job_data.get("title")
        company = job_data.get("company")
        link = job_data.get("link")

        print_lg(f"\n[Glassdoor] ----------------------------------------------------")
        print_lg(f"[Glassdoor] Evaluating: '{title}' at '{company}'")

        bad_words = getattr(search, "bad_words", [])
        for bad in bad_words:
            if bad and bad.lower() in title.lower():
                print_lg(f"[Glassdoor] ⏭️ Skipping: Title contains '{bad}'")
                self.skipped_count += 1
                return False

        try:
            # Locate Easy Apply button in the detail pane
            easy_apply_btn = self.page.locator(
                "button[data-test='easy-apply-button'], button:has-text('Easy Apply'), button:has-text('Apply on Glassdoor')"
            ).first

            if easy_apply_btn.count() == 0 or not easy_apply_btn.is_visible():
                print_lg(f"[Glassdoor] ⏭️ No direct Easy Apply button. Skipping external site.")
                self.skipped_count += 1
                return False

            print_lg(f"[Glassdoor] 🎯 Clicked 'Easy Apply'. Filling application form...")
            easy_apply_btn.click()
            self.human_delay(2, 3)

            # Application steps
            success = self.handle_glassdoor_wizard(job_data)
            if success:
                self.record_application(
                    job_id=job_data.get("id"),
                    title=title,
                    company=company,
                    job_link=link,
                    external_link="Glassdoor Easy Applied"
                )
                return True
            else:
                self.failed_count += 1
                return False
        except Exception as e:
            print_lg(f"[Glassdoor] Apply error: {e}")
            self.failed_count += 1
            return False

    def handle_glassdoor_wizard(self, job_data: Dict[str, Any]) -> bool:
        max_steps = 10
        step_num = 0

        while step_num < max_steps:
            step_num += 1
            self.human_delay(2, 3)

            # Success indicators
            success_loc = self.page.locator("h3:has-text('Application submitted'), div:has-text('Your application has been sent')")
            if success_loc.count() > 0:
                print_lg("🎉 [Glassdoor] Application submitted successfully!")
                return True

            # Fill inputs
            self.fill_form_inputs(job_data)

            # Check Submit
            submit_btn = self.page.locator("button:has-text('Submit Application'), button:has-text('Submit'), button[data-test='submit-button']").first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                if self.stop_before_submit:
                    print_lg("[Glassdoor] Paused at review screen (dry-run mode).")
                    return True
                print_lg("[Glassdoor] 🚀 Submitting application...")
                submit_btn.click()
                self.human_delay(3, 4)
                return True

            # Click Continue / Next
            next_btn = self.page.locator("button:has-text('Continue'), button:has-text('Next'), button[data-test='continue-button']").first
            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click()
            else:
                break
        return False

    def fill_form_inputs(self, job_data: Dict[str, Any]):
        fname = getattr(personals, "first_name", "")
        lname = getattr(personals, "last_name", "")
        phone = getattr(personals, "phone_number", "")
        city = getattr(personals, "current_city", "")

        inputs = self.page.locator("input[type='text'], input[type='tel'], input[type='number'], textarea").all()
        for inp in inputs:
            try:
                if not inp.is_visible() or inp.input_value():
                    continue
                label_text = (inp.get_attribute("aria-label") or inp.get_attribute("name") or "").lower()
                if "first" in label_text:
                    inp.fill(fname)
                elif "last" in label_text:
                    inp.fill(lname)
                elif "phone" in label_text or "tel" in label_text:
                    inp.fill(phone)
                elif "city" in label_text:
                    inp.fill(city)
                elif "experience" in label_text:
                    inp.fill(str(getattr(questions, "years_of_experience", "3")))
                else:
                    if ai_client and label_text:
                        ans = answer_question(ai_client, label_text, None, "text", job_data.get("title", ""), job_data.get("company", ""), f"{fname} {lname}, {city}")
                        inp.fill(ans)
                    else:
                        inp.fill("3")
            except Exception:
                continue

    def run(self):
        self.is_running = True
        print_lg("\n=======================================================")
        print_lg("         🟢 STARTING GLASSDOOR AUTO JOB APPLIER")
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

        print_lg(f"\n[Glassdoor] Finished: {self.applied_count} Applied, {self.skipped_count} Skipped, {self.failed_count} Failed.")
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
    bot = GlassdoorBot()
    bot.run()
