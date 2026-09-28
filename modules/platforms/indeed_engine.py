'''
Indeed Job Application Engine.
Integrates patterns from meteor314/indeed_bot and RayeesYousufGenAi multi-platform handler
with AI question-answering, persistent browser sessions, and unified tracking.
'''

import os
import re
import sys
import time
import random
import urllib.parse
from datetime import datetime, timedelta
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
        print_lg(f"[Indeed] Note: Could not initialize AI client: {e}")


class IndeedBot(BasePlatformBot):
    '''Automated Job Applier for Indeed featuring stealth navigation and AI form answering.'''

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(platform_name="Indeed", config=config)
        self.driver = None
        self.playwright = None
        self.browser = None
        self.page = None
        self.context = None
        self.user_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../userData/indeed_profile"))
        os.makedirs(self.user_data_dir, exist_ok=True)
        
        self.country_domain = getattr(secrets, "indeed_country_domain", "www.indeed.com") or "www.indeed.com"
        self.base_url = getattr(search, "indeed_base_url", "")
        self.search_terms = getattr(search, "search_terms", ["Software Engineer"])
        self.search_location = getattr(search, "search_location", "")
        self.stop_before_submit = getattr(settings, "stop_before_submit", False)
        self.click_gap = getattr(settings, "click_gap", 2)
        self.safe_mode = getattr(settings, "safe_mode", False)
        self.run_in_background = getattr(settings, "run_in_background", False)

    def initialize_browser(self):
        '''Initialize Playwright browser with persistent context and stealth evasion.'''
        print_lg("[Indeed] Initializing browser engine with anti-detection...")
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                print_lg("[Indeed] Playwright package not found. Installing playwright and chromium automatically...")
                import subprocess
                subprocess.run([sys.executable, "-m", "pip", "install", "playwright", "playwright-stealth"], check=True)
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                from playwright.sync_api import sync_playwright
                print_lg("[Indeed] Playwright & Chromium installed successfully!")

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

            print_lg(f"[Indeed] Browser successfully initialized. Session stored at: {self.user_data_dir}")
            return True
        except Exception as e:
            print_lg(f"[Indeed] Error initializing Playwright engine: {e}")
            critical_error_log("Failed to start Indeed browser", e)
            return False

    def human_delay(self, min_sec: float = 1.0, max_sec: float = 2.5):
        '''Simulate natural human timing.'''
        gap = max(self.click_gap, 1)
        time.sleep(random.uniform(min_sec * gap, max_sec * gap))

    def is_logged_in(self) -> bool:
        '''Check if the session is currently authenticated on Indeed.'''
        logged_in_selectors = [
            "button[data-gnav-element='user-avatar']",
            "a[data-gnav-element='profile']",
            "a[href*='/account']",
            "#AccountMenu",
            "div[data-testid='account-menu']",
            "a[href*='/m/notifications']",
            "a[data-gnav-element='notifications']",
            "[data-gnav-element='profile-dropdown']"
        ]
        for selector in logged_in_selectors:
            try:
                loc = self.page.locator(selector)
                if loc.count() > 0 and loc.first.is_visible():
                    return True
            except Exception:
                continue
        # Also check if URL is past login page and on standard indeed pages
        url = self.page.url.lower()
        if "indeed.com" in url and not any(p in url for p in ["/account/login", "/auth", "/login", "/challenge"]):
            # Check for absence of sign-in button
            signin_loc = self.page.locator("a[href*='/account/login'], a:has-text('Sign in'), a:has-text('Connexion')")
            if signin_loc.count() == 0:
                return True
        return False

    def login(self) -> bool:
        '''
        Check login status or guide the user to log in via Google, Apple, or Email OTP code.
        The persistent browser session will remember the login for all subsequent runs.
        '''
        print_lg(f"[Indeed] Checking session state at https://{self.country_domain}...")
        try:
            self.page.goto(f"https://{self.country_domain}", wait_until="domcontentloaded", timeout=60000)
            self.human_delay(2, 3)

            if self.is_logged_in():
                print_lg("✅ [Indeed] Logged in via saved persistent session!")
                return True

            print_lg("\n=======================================================")
            print_lg("🔑 [Indeed] ONE-TIME LOGIN REQUIRED")
            print_lg("👉 Indeed uses Google Sign-In, Apple, or Email verification code (OTP).")
            print_lg("👉 Please complete sign-in in the open browser window.")
            print_lg("👉 The bot is waiting and will automatically continue once signed in...")
            print_lg("=======================================================\n")

            # Try navigating to sign-in page if not already there
            signin_btn = self.page.locator("a[href*='/account/login'], a:has-text('Sign in'), a:has-text('Connexion')").first
            if signin_btn.count() > 0 and signin_btn.is_visible():
                try:
                    signin_btn.click()
                    self.human_delay(2, 3)
                except Exception:
                    pass

            # Pre-fill email if provided to speed up Google / Email code entry
            username = getattr(secrets, "indeed_username", "") or getattr(secrets, "username", "")
            if username:
                try:
                    email_input = self.page.locator("input[type='email'], input[name='__email'], #ifl-InputFormField-3").first
                    if email_input.count() > 0 and email_input.is_visible():
                        email_input.fill(username)
                        self.human_delay(1, 1.5)
                        submit_btn = self.page.locator("button[type='submit']").first
                        if submit_btn.count() > 0 and submit_btn.is_visible():
                            submit_btn.click()
                except Exception:
                    pass

            # Wait loop for user to finish Google / OTP / Apple login
            max_wait_seconds = 180
            start_time = time.time()
            notified_halfway = False

            while time.time() - start_time < max_wait_seconds:
                if not self.is_running:
                    print_lg("[Indeed] Stop requested during login wait.")
                    return False

                if self.is_logged_in():
                    print_lg("\n✅ [Indeed] Sign in detected! Session successfully saved to persistent profile.")
                    print_lg("[Indeed] Future runs will not require sign-in.")
                    self.human_delay(2, 3)
                    return True

                elapsed = int(time.time() - start_time)
                if elapsed > 30 and not notified_halfway:
                    print_lg(f"[Indeed] Still waiting for login... ({max_wait_seconds - elapsed}s remaining). Please finish Google/OTP sign-in in browser.")
                    notified_halfway = True

                time.sleep(3)

            print_lg("⚠️ [Indeed] Login wait timed out. Continuing to search jobs, but some applications may require login.")
            return False
        except Exception as e:
            print_lg(f"[Indeed] Login verification notice: {e}")
            return False

    def build_search_url(self, keyword: str, location: str) -> str:
        '''Generate Indeed search URL with standard filters.'''
        if self.base_url:
            return self.base_url

        params = {"q": keyword}
        if location:
            params["l"] = location
            
        # Optional date filter: 'Past 24 hours' (1), 'Past week' (7), 'Past month' (14/30)
        date_posted = getattr(search, "date_posted", "")
        if "24 hours" in date_posted:
            params["fromage"] = "1"
        elif "week" in date_posted:
            params["fromage"] = "7"
        elif "month" in date_posted:
            params["fromage"] = "14"

        query_str = urllib.parse.urlencode(params)
        return f"https://{self.country_domain}/jobs?{query_str}&sort=date"

    def search_jobs(self) -> List[Dict[str, Any]]:
        '''Find all job postings across configured search terms.'''
        all_jobs = []
        for term in self.search_terms:
            search_url = self.build_search_url(term, self.search_location)
            try:
                self.page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                cards = self.page.locator("div.job_seen_beacon, div.cardOutline, div[data-testid='slider_item']").all()
                for idx, card in enumerate(cards):
                    title_el = card.locator("h2.jobTitle span, a[data-jk] span").first
                    title = title_el.text_content().strip() if title_el.count() > 0 else f"Job #{idx+1}"
                    all_jobs.append({"title": title, "card": card})
            except Exception:
                continue
        return all_jobs

    def search_and_apply_term(self, term: str, max_apps: int = 25):
        '''Search for a specific keyword and apply to matching jobs immediately.'''
        search_url = self.build_search_url(term, self.search_location)
        print_lg(f"\n=======================================================")
        print_lg(f"🔍 [Indeed] Searching for: '{term}' in '{self.search_location or 'Anywhere'}'")
        print_lg(f"🔗 URL: {search_url}")
        print_lg("=======================================================\n")

        try:
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            self.human_delay(3, 4)
        except Exception as e:
            print_lg(f"[Indeed] Notice loading search page for '{term}': {e}")
            try:
                self.page.goto(search_url, timeout=60000)
                self.human_delay(2, 3)
            except Exception:
                return

    def find_apply_button(self, target_page):
        '''Locate the Indeed Apply / Apply Now button across all modern Indeed DOM variants.'''
        selectors = [
            "#indeedApplyButton",
            "button[id*='indeedApplyButton']",
            "button[data-testid='indeedApplyButton']",
            "button[data-testid='viewJob-apply-button']",
            "[data-testid='indeedApply']",
            "div[id='applyButtonLinkContainer'] button",
            "div[id='applyButtonLinkContainer'] a",
            "div.jobsearch-IndeedApplyButton-contentWrapper",
            "button:has-text('Apply now')",
            "a:has-text('Apply now')",
            "span:has-text('Apply now')",
            "button:has-text('Easily apply')",
            "a:has-text('Easily apply')",
            "span:has-text('Easily apply')",
            "button:has-text('Postuler dès maintenant')",
            "button[aria-label*='Apply now' i]",
            "button[aria-label*='Easily apply' i]",
            "button[aria-label*='Apply' i]",
            "a[aria-label*='Apply' i]"
        ]
        for sel in selectors:
            try:
                loc = target_page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    def search_and_apply_term(self, term: str, max_apps: int = 25):
        '''Search for a specific keyword and apply to matching jobs immediately in dedicated tabs.'''
        search_url = self.build_search_url(term, self.search_location)
        print_lg(f"\n=======================================================")
        print_lg(f"🔍 [Indeed] Searching for: '{term}' in '{self.search_location or 'Anywhere'}'")
        print_lg(f"🔗 URL: {search_url}")
        print_lg("=======================================================\n")

        try:
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            self.human_delay(3, 4)
        except Exception as e:
            print_lg(f"[Indeed] Notice loading search page for '{term}': {e}")
            try:
                self.page.goto(search_url, timeout=60000)
                self.human_delay(2, 3)
            except Exception:
                return

        # Find all job cards on current search page
        card_selectors = "div.job_seen_beacon, div.cardOutline, div[data-testid='slider_item'], li.css-5lfssm"
        try:
            self.page.wait_for_selector(card_selectors, timeout=10000)
        except Exception:
            pass

        cards = self.page.locator(card_selectors).all()
        print_lg(f"[Indeed] Found {len(cards)} listings on page for '{term}'. Extracting job links...")

        # Extract all job details into a detached list first so DOM updates don't break iteration
        jobs_to_process = []
        for idx, card in enumerate(cards):
            try:
                title_el = card.locator("h2.jobTitle span, a[data-jk] span, h2.jobTitle a").first
                title = title_el.text_content().strip() if title_el.count() > 0 else f"Job #{idx+1}"

                company_el = card.locator("[data-testid='company-name'], span.css-63koeb, span.companyName").first
                company = company_el.text_content().strip() if company_el.count() > 0 else "Unknown Company"

                link_el = card.locator("a[data-jk], h2.jobTitle a").first
                jk = link_el.get_attribute("data-jk") if link_el.count() > 0 else None
                if jk:
                    job_link = f"https://{self.country_domain}/viewjob?jk={jk}"
                else:
                    href = link_el.get_attribute("href") if link_el.count() > 0 else ""
                    job_link = urllib.parse.urljoin(f"https://{self.country_domain}", href) if href else ""

                if job_link:
                    jobs_to_process.append({
                        "id": jk or f"indeed_{int(time.time())}_{idx}",
                        "title": title,
                        "company": company,
                        "link": job_link
                    })
            except Exception:
                continue

        print_lg(f"[Indeed] Ready to process {len(jobs_to_process)} job links for '{term}'.")

        term_applied = 0
        for job_data in jobs_to_process:
            if not self.is_running:
                print_lg("[Indeed] Stop requested. Halting search loop.")
                break
            if term_applied >= max_apps:
                print_lg(f"[Indeed] Reached limit of {max_apps} applications for '{term}'. Switching search term.")
                break

            applied = self.apply_to_job(job_data)
            if applied:
                term_applied += 1
            self.human_delay(2, 4)

    def apply_to_job(self, job_data: Dict[str, Any]) -> bool:
        '''
        Opens an Indeed job listing in a dedicated tab, launches the application wizard, answers questions,
        and submits the application.
        '''
        job_id = job_data.get("id")
        title = job_data.get("title")
        company = job_data.get("company")
        link = job_data.get("link")

        print_lg(f"\n[Indeed] ----------------------------------------------------")
        print_lg(f"[Indeed] Evaluating: '{title}' at '{company}'")

        # Check blacklist words
        bad_words = getattr(search, "bad_words", [])
        for bad in bad_words:
            if bad and bad.lower() in title.lower():
                print_lg(f"[Indeed] ⏭️ Skipping job: title matches excluded keyword '{bad}'")
                self.skipped_count += 1
                return False

        job_tab = None
        try:
            # Open the job in a dedicated tab to avoid disturbing the search results page
            job_tab = self.context.new_page()
            job_tab.goto(link, wait_until="domcontentloaded", timeout=35000)
            self.human_delay(2, 3)

            # Locate Apply Now button
            apply_btn = self.find_apply_button(job_tab)
            if not apply_btn:
                print_lg(f"[Indeed] ⏭️ No direct 'Apply now' / 'Easily apply' button found. Skipping.")
                self.skipped_count += 1
                job_tab.close()
                return False

            print_lg(f"[Indeed] 🎯 Clicked 'Apply now' for '{title}'. Launching application wizard...")
            
            # Clicking Apply can open a popup page/tab OR a modal in the job tab
            target_page = job_tab
            try:
                with self.context.expect_page(timeout=4000) as page_info:
                    apply_btn.click()
                popup = page_info.value
                popup.wait_for_load_state("domcontentloaded", timeout=15000)
                target_page = popup
                print_lg("[Indeed] Application wizard opened in popup tab.")
            except Exception:
                # Opened in modal on the same tab
                pass

            self.human_delay(2, 3)
            success = self.handle_application_wizard(target_page, job_data)

            # Close popup page if opened
            if target_page != job_tab:
                try:
                    target_page.close()
                except Exception:
                    pass

            job_tab.close()

            if success:
                self.record_application(
                    job_id=job_id,
                    title=title,
                    company=company,
                    job_link=link,
                    external_link="Indeed Applied"
                )
                return True
            else:
                self.failed_count += 1
                return False
        except Exception as e:
            print_lg(f"[Indeed] Error applying to '{title}': {e}")
            self.failed_count += 1
            if job_tab:
                try:
                    job_tab.close()
                except Exception:
                    pass
            return False

    def safe_click(self, locator, page):
        '''Safely clicks a locator, using force click and JavaScript execution to bypass sticky footers and overlay intercepts.'''
        if not locator or locator.count() == 0:
            return False
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            locator.click(timeout=3000)
            return True
        except Exception:
            try:
                locator.click(force=True, timeout=3000)
                return True
            except Exception:
                try:
                    handle = locator.element_handle()
                    if handle:
                        page.evaluate("(el) => el.click()", handle)
                        return True
                except Exception:
                    pass
        return False

    def handle_application_wizard(self, page, job_data: Dict[str, Any]) -> bool:
        '''
        Loops through the multi-page Indeed Application Wizard.
        Fills contact info, selects CV, answers questions using AI/heuristics, and submits.
        Waits up to 10 seconds per step for dynamic questionnaires to render.
        '''
        max_steps = 15
        step_num = 0

        while step_num < max_steps:
            step_num += 1
            print_lg(f"[Indeed] Step {step_num}: Loading and evaluating step content...")
            
            # Allow dynamic step content / AJAX questions to load (up to 10 seconds)
            submit_selectors = [
                "button:has-text('Submit your application')",
                "button:has-text('Submit application')",
                "button:has-text('Postuler')",
                "button[type='submit']:has-text('Submit')",
                "button[data-testid='submit-application-button']",
                "button:has-text('Submit')"
            ]
            continue_selectors = [
                "button:has-text('Continue')",
                "button:has-text('Next')",
                "button:has-text('Review your application')",
                "button:has-text('Continuer')",
                "button:has-text('Suivant')",
                "button.ia-continueButton",
                "button[data-testid='continue-button']"
            ]
            success_indicators = [
                "h1:has-text('Application submitted')",
                "h1:has-text('Your application has been submitted')",
                "div:has-text('Application sent')",
                "div:has-text('Your application was submitted')",
                "h1:has-text('Candidature envoyée')",
                "[data-testid='application-submitted']"
            ]

            # Wait loop up to 10s for interactive elements to appear on the step
            found_interactive = False
            for w in range(10):
                # Check for success
                for succ in success_indicators:
                    if page.locator(succ).count() > 0:
                        print_lg("🎉 [Indeed] Application successfully submitted!")
                        return True

                # Check if submit or continue or questions exist
                for sel in submit_selectors + continue_selectors:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        found_interactive = True
                        break
                
                if found_interactive:
                    break
                time.sleep(1)

            # Scroll down to ensure all questions and bottom action buttons are in DOM
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2);")
                self.human_delay(1, 1.5)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                self.human_delay(1, 1.5)
            except Exception:
                pass

            # 1. Answer All Employer Screening Questions & Form Inputs
            self.answer_screening_questions(page, job_data)

            # 2. Select Resume if present on this step
            self.handle_resume_step(page)

            # Scroll down again after answering
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                self.human_delay(1, 1.5)
            except Exception:
                pass

            # 3. Check for Review Step / Submit Button
            submit_btn = None
            for sel in submit_selectors:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    submit_btn = loc
                    break

            if submit_btn:
                print_lg("[Indeed] 📋 Reached Review & Submit screen.")
                if self.stop_before_submit:
                    print_lg("[Indeed] 'Stop before submit' is active. Pausing at review screen without submitting.")
                    return True
                
                print_lg("[Indeed] 🚀 Submitting application now...")
                self.safe_click(submit_btn, page)
                self.human_delay(4, 6)
                
                # Verify submission confirmation
                for _ in range(5):
                    for succ in success_indicators:
                        if page.locator(succ).count() > 0:
                            print_lg("🎉 [Indeed] Application successfully submitted!")
                            return True
                    time.sleep(1)
                return True

            # 4. Click Continue / Next / Review
            continue_btn = None
            for sel in continue_selectors:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    continue_btn = loc
                    break

            if continue_btn:
                print_lg(f"[Indeed] Step {step_num}: Advancing to next step...")
                clicked = self.safe_click(continue_btn, page)
                if not clicked:
                    try:
                        page.keyboard.press("Enter")
                    except Exception:
                        pass
                # Wait for next step to start loading
                self.human_delay(3, 4)
            else:
                # One last check for success before exiting
                for succ in success_indicators:
                    if page.locator(succ).count() > 0:
                        print_lg("🎉 [Indeed] Application successfully submitted!")
                        return True
                print_lg(f"[Indeed] Step {step_num}: No continue button visible after wait. Finishing step evaluation.")
                break

        return False

    def answer_screening_questions(self, page, job_data: Dict[str, Any]):
        '''
        Intelligently resolves and fills all employer screening questions on the current step:
        - Radio button groups (Age 18+, Work auth, Sponsorship, Driving license, Relationships, etc.)
        - Dropdown / Select menus
        - Checkboxes
        - Text / Numeric / Textarea inputs
        - AI model fallback for unknown complex questions
        '''
        fname = getattr(personals, "first_name", "")
        lname = getattr(personals, "last_name", "")
        phone = getattr(personals, "phone_number", "")
        city = getattr(personals, "current_city", "")

        # -------------------------------------------------------------
        # A. RADIO GROUPS & FIELDSETS
        # -------------------------------------------------------------
        group_selectors = [
            "fieldset",
            "div[role='radiogroup']",
            "div.ia-Questions-item",
            "div[data-testid*='question']",
            "div[data-testid='QuestionSection']",
            "div[class*='Questions-item']"
        ]
        
        handled_elements = set()
        for g_sel in group_selectors:
            groups = page.locator(g_sel).all()
            for grp in groups:
                try:
                    if not grp.is_visible():
                        continue
                    
                    # Extract prompt text for this question
                    legend_el = grp.locator("legend, [id*='label'], h3, h4, span.css-1r0f1l7, label").first
                    q_text = legend_el.text_content().strip() if legend_el.count() > 0 else grp.text_content()[:200].strip()
                    q_lower = q_text.lower()

                    # Find radio options inside this group
                    radios = grp.locator("input[type='radio']").all()
                    labels = grp.locator("label").all()
                    
                    if len(radios) > 0 or len(labels) > 0:
                        # Determine intended answer
                        chosen_opt = None
                        
                        # Rule 1: Age 18+
                        if any(w in q_lower for w in ["18 years", "at least 18", "18 or older", "age or older", "legal age"]):
                            chosen_opt = "yes"
                        # Rule 2: United States Citizen / Citizenship
                        elif any(w in q_lower for w in ["united states citizen", "u.s. citizen", "us citizen", "are you a citizen"]):
                            citizen_status = getattr(questions, "us_citizenship", "U.S. Citizen/Permanent Resident")
                            chosen_opt = "yes" if "citizen" in citizen_status.lower() else "no"
                        # Rule 3: Conduct work from within US / Location
                        elif any(w in q_lower for w in ["conduct all work", "within the united states", "work from within"]):
                            chosen_opt = "yes"
                        # Rule 4: Public Trust / SF-85P / Suitability / Investigation / Security Clearance
                        elif any(w in q_lower for w in ["public trust", "sf-85p", "sf85", "suitability", "investigation if required", "security clearance"]):
                            chosen_opt = "yes"
                        # Rule 5: Outside employment policy / Compliance
                        elif any(w in q_lower for w in ["outside employment", "permission from senior management", "will you comply", "comply with this requirement"]):
                            chosen_opt = "yes"
                        # Rule 6: Legally permitted / authorized to work
                        elif any(w in q_lower for w in ["legally permitted", "authorized to work", "legal right to work", "legally authorized", "work authorization"]):
                            auth = getattr(questions, "legally_authorized", "Yes")
                            chosen_opt = "yes" if auth.lower() == "yes" else "no"
                        # Rule 7: Visa sponsorship
                        elif any(w in q_lower for w in ["sponsorship", "require visa", "h-1b", "visa status", "employment visa"]):
                            need_visa = getattr(questions, "require_visa", "No")
                            chosen_opt = "yes" if need_visa.lower() == "yes" else "no"
                        # Rule 8: Criminal history / convictions / pending charges
                        elif any(w in q_lower for w in ["convicted", "pled guilty", "nolo contendere", "crime", "felony", "misdemeanor", "criminal charge", "charges pending"]):
                            chosen_opt = "no"
                        # Rule 9: Able to perform duties / reasonable accommodation
                        elif any(w in q_lower for w in ["perform the duties", "perform the essential", "reasonable accommodation", "essential functions", "able to perform"]):
                            chosen_opt = "yes"
                        # Rule 10: Previously employed / former employee / worked here
                        elif any(w in q_lower for w in ["previously employed", "ever been employed", "former employee", "worked for", "worked at", "employed at"]):
                            chosen_opt = "no"
                        # Rule 11: Terminated / asked to resign
                        elif any(w in q_lower for w in ["terminated", "asked to resign", "discharged"]):
                            chosen_opt = "no"
                        # Rule 12: Driver's license / reliable transportation / driving
                        elif any(w in q_lower for w in ["driver's license", "drivers license", "driving", "reliable transportation", "proof of auto insurance"]):
                            chosen_opt = "yes"
                        # Rule 13: Relationship / conflict of interest
                        elif any(w in q_lower for w in ["relationship", "romantic", "familial", "conflict of interest", "relative", "related to"]):
                            chosen_opt = "no"
                        # Rule 14: Supplier / vendor / contractor
                        elif any(w in q_lower for w in ["supplier", "vendor", "contractor", "subcontractor"]):
                            chosen_opt = "no"
                        # Rule 15: Background check / drug screen
                        elif any(w in q_lower for w in ["background check", "drug screen", "drug test", "substance"]):
                            chosen_opt = "yes"
                        # Rule 16: Tuberculosis / medical / health screening
                        elif any(w in q_lower for w in ["tuberculosis", "tb screening", "tb test", "medical screening", "member facing"]):
                            chosen_opt = "yes"
                        # Rule 17: Text messages / SMS job alerts opt in
                        elif any(w in q_lower for w in ["text message", "sms", "opt in to receive", "receive text"]):
                            chosen_opt = "yes"
                        # Rule 18: Willing to commute / relocate / work schedule / overtime / hybrid
                        elif any(w in q_lower for w in ["commute", "relocate", "hybrid", "on-site", "overtime", "weekends", "washington"]):
                            chosen_opt = "yes"
                        # Rule 19: Education / high school / degree
                        elif any(w in q_lower for w in ["high school", "bachelor", "degree", "diploma", "graduated"]):
                            chosen_opt = "yes"
                        else:
                            # Fallback to AI if available, otherwise default to Yes
                            if ai_client and len(q_text) > 10:
                                opt_texts = [lbl.text_content().strip() for lbl in labels if lbl.text_content().strip()]
                                print_lg(f"[Indeed] 🤖 AI answering radio question: '{q_text[:60]}...'")
                                user_info = f"Name: {fname} {lname}, Phone: {phone}, City: {city}, Experience: {getattr(questions, 'years_of_experience', 3)} yrs"
                                ans = answer_question(
                                    ai_client,
                                    question=q_text,
                                    options=opt_texts if opt_texts else ["Yes", "No", "True", "False"],
                                    question_type="multiple_choice",
                                    job_description=job_data.get("title", ""),
                                    about_company=job_data.get("company", ""),
                                    user_information=user_info
                                )
                                chosen_opt = "yes" if any(k in ans.lower() for k in ["yes", "true"]) else ("no" if any(k in ans.lower() for k in ["no", "false"]) else ans.lower())
                            else:
                                chosen_opt = "yes"

                        # Click the chosen radio or label (supports Yes/No and True/False)
                        matched_click = False
                        for lbl in labels:
                            lbl_text = lbl.text_content().strip().lower()
                            if chosen_opt == "yes" and any(lbl_text == w or lbl_text.startswith(w) for w in ["yes", "true", "oui", "vrai"]):
                                self.safe_click(lbl, page)
                                matched_click = True
                                break
                            elif chosen_opt == "no" and any(lbl_text == w or lbl_text.startswith(w) for w in ["no", "false", "non", "faux"]):
                                self.safe_click(lbl, page)
                                matched_click = True
                                break
                            elif chosen_opt in lbl_text:
                                self.safe_click(lbl, page)
                                matched_click = True
                                break

                        if not matched_click and len(radios) > 0:
                            if chosen_opt == "yes":
                                self.safe_click(radios[0], page)
                            elif chosen_opt == "no" and len(radios) > 1:
                                self.safe_click(radios[1], page)
                            else:
                                self.safe_click(radios[0], page)
                except Exception:
                    continue

        # -------------------------------------------------------------
        # B. CHECKBOXES (Citizenship countries, agreements, acknowledgements)
        # -------------------------------------------------------------
        checkbox_groups = page.locator("fieldset:has(input[type='checkbox']), div[class*='Questions']:has(input[type='checkbox']), div[role='group']:has(input[type='checkbox'])").all()
        for c_grp in checkbox_groups:
            try:
                if not c_grp.is_visible():
                    continue
                grp_text = c_grp.text_content().lower()
                cboxes = c_grp.locator("input[type='checkbox']").all()
                clabels = c_grp.locator("label").all()

                if "country of which you are a citizen" in grp_text or "citizen" in grp_text:
                    # Select United States of America
                    us_clicked = False
                    for clbl in clabels:
                        lbl_t = clbl.text_content().strip().lower()
                        if any(k in lbl_t for k in ["united states", "usa", "america"]):
                            self.safe_click(clbl, page)
                            us_clicked = True
                            break
                    if not us_clicked and len(cboxes) > 0:
                        self.safe_click(cboxes[0], page)
                else:
                    # If required checkboxes (e.g. acknowledge/agree)
                    for idx, cb in enumerate(cboxes):
                        try:
                            if not cb.is_checked():
                                if idx < len(clabels):
                                    self.safe_click(clabels[idx], page)
                                else:
                                    self.safe_click(cb, page)
                        except Exception:
                            pass
            except Exception:
                continue

        # -------------------------------------------------------------
        # C. DROPDOWNS / SELECTS
        # -------------------------------------------------------------
        selects = page.locator("select").all()
        for sel in selects:
            try:
                if not sel.is_visible() or not sel.is_enabled():
                    continue
                
                # Check label
                sel_id = sel.get_attribute("id") or ""
                label_text = ""
                if sel_id:
                    lbl = page.locator(f"label[for='{sel_id}']").first
                    if lbl.count() > 0:
                        label_text = lbl.text_content().lower()

                options = sel.locator("option").all()
                opt_texts = [opt.text_content().strip() for opt in options if opt.text_content().strip()]
                
                if any(w in label_text for w in ["sponsor", "visa"]):
                    need_visa = getattr(questions, "require_visa", "No")
                    sel.select_option(label=need_visa)
                elif any(w in label_text for w in ["authorized", "legally"]):
                    auth = getattr(questions, "legally_authorized", "Yes")
                    sel.select_option(label=auth)
                elif any(w in label_text for w in ["standardized", "admissions test", "sat", "act", "gre", "gmat"]):
                    # Standardized test dropdown (SAT, ACT, GRE, GMAT, None)
                    selected_test = False
                    for test_name in ["SAT", "GRE", "ACT", "GMAT", "None", "Not Applicable"]:
                        for opt_t in opt_texts:
                            if test_name.lower() in opt_t.lower():
                                sel.select_option(label=opt_t)
                                selected_test = True
                                break
                        if selected_test:
                            break
                    if not selected_test and len(options) > 1:
                        sel.select_option(index=1)
                elif any(w in label_text for w in ["convict", "felon", "crime", "charge"]):
                    try:
                        sel.select_option(label="No")
                    except Exception:
                        sel.select_option(index=1)
                elif any(w in label_text for w in ["citizen", "citizenship"]):
                    citizenship = getattr(questions, "us_citizenship", "U.S. Citizen/Permanent Resident")
                    try:
                        sel.select_option(label=citizenship)
                    except Exception:
                        if len(options) > 1:
                            sel.select_option(index=1)
                else:
                    # Select 'Yes' option if available or index 1
                    try:
                        sel.select_option(label="Yes")
                    except Exception:
                        if len(options) > 1:
                            sel.select_option(index=1)
            except Exception:
                continue

        # -------------------------------------------------------------
        # D. TEXT / NUMBER / DATE / TEXTAREA INPUTS
        # -------------------------------------------------------------
        inputs = page.locator("input[type='text'], input[type='tel'], input[type='number'], input[type='date'], textarea").all()
        for inp in inputs:
            try:
                if not inp.is_visible() or not inp.is_enabled():
                    continue
                current_val = inp.input_value()
                if current_val:
                    continue  # already has value

                name_attr = (inp.get_attribute("name") or "").lower()
                id_attr = (inp.get_attribute("id") or "").lower()
                aria_label = (inp.get_attribute("aria-label") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                is_required = inp.get_attribute("required") or inp.get_attribute("aria-required") == "true"
                
                label_text = ""
                if id_attr:
                    label_el = page.locator(f"label[for='{id_attr}']").first
                    if label_el.count() > 0:
                        label_text = label_el.text_content().lower()

                field_hint = f"{name_attr} {id_attr} {aria_label} {placeholder} {label_text}"
                if "*" in label_text:
                    is_required = True

                if any(k in field_hint for k in ["first", "firstname", "prénom"]):
                    inp.fill(fname)
                elif any(k in field_hint for k in ["last", "lastname", "nom"]):
                    inp.fill(lname)
                elif any(k in field_hint for k in ["phone", "tel", "mobile"]):
                    inp.fill(phone)
                elif any(k in field_hint for k in ["city", "location", "ville"]):
                    inp.fill(city)
                elif any(k in field_hint for k in ["other country", "other countries", "if you selected other"]):
                    inp.fill("N/A")
                elif any(k in field_hint for k in ["sat score", "gre score", "act score", "gmat score", "test score", "score:"]):
                    inp.fill("1400")
                elif any(k in field_hint for k in ["availability", "start date", "earliest start", "available to start", "start_date"]):
                    target_date = datetime.now() + timedelta(days=20)
                    input_type = (inp.get_attribute("type") or "text").lower()
                    if input_type == "date":
                        inp.fill(target_date.strftime("%Y-%m-%d"))
                    else:
                        inp.fill(target_date.strftime("%m/%d/%Y"))
                elif any(k in field_hint for k in ["annual salary", "pay", "salary", "compensation", "ctc", "rate", "expectation", "expected pay"]):
                    sal = str(getattr(questions, "desired_salary", "80000"))
                    inp.fill(sal)
                elif any(k in field_hint for k in ["language", "proficien", "english"]):
                    inp.fill("English")
                elif any(k in field_hint for k in ["experience", "years"]):
                    years = str(getattr(questions, "years_of_experience", "5"))
                    inp.fill(years)
                elif any(k in field_hint for k in ["notice", "days"]):
                    notice = str(getattr(questions, "notice_period", "30"))
                    inp.fill(notice)
                elif any(k in field_hint for k in ["website", "portfolio", "url"]):
                    site = getattr(questions, "website", "") or getattr(questions, "linkedIn", "")
                    inp.fill(site)
                else:
                    if ai_client and label_text:
                        print_lg(f"[Indeed] 🤖 AI answering text question: '{label_text.strip()}'")
                        user_info = f"Name: {fname} {lname}, Phone: {phone}, City: {city}, Experience: {getattr(questions, 'years_of_experience', 3)} yrs"
                        ans = answer_question(
                            ai_client,
                            question=label_text,
                            options=None,
                            question_type="text",
                            job_description=job_data.get("title", ""),
                            about_company=job_data.get("company", ""),
                            user_information=user_info
                        )
                        inp.fill(ans)
                    elif is_required:
                        inp.fill("N/A")
                    else:
                        inp.fill("5")
            except Exception:
                continue

    def handle_resume_step(self, page):
        '''Select saved Indeed profile resume or upload local PDF resume.'''
        try:
            resume_options = page.locator(
                "div[data-testid='resume-card'], "
                "label[data-testid*='resume'], "
                "div[data-testid='FileDisplay'], "
                "input[type='radio'][name*='resume']"
            ).all()
            
            if len(resume_options) > 0:
                first_option = resume_options[0]
                if first_option.is_visible():
                    self.safe_click(first_option, page)
                    self.human_delay(1, 2)
                    return

            file_input = page.locator("input[type='file']").first
            if file_input.count() > 0:
                resume_path = getattr(questions, "default_resume_path", "all resumes/default/resume.pdf")
                abs_path = os.path.abspath(resume_path)
                if os.path.exists(abs_path):
                    file_input.set_input_files(abs_path)
                    print_lg(f"[Indeed] Uploaded resume file from {abs_path}")
                    self.human_delay(1, 2)
        except Exception:
            pass

    def run(self):
        '''Main loop: initialize, log in, search, and apply per search term.'''
        self.is_running = True
        print_lg("\n=======================================================")
        print_lg("         🚀 STARTING INDEED AUTO JOB APPLIER")
        print_lg("=======================================================\n")

        if not self.initialize_browser():
            print_lg("[Indeed] Failed to initialize browser. Halting.")
            return

        self.login()

        switch_number = getattr(search, "switch_number", 25)
        for term in self.search_terms:
            if not self.is_running:
                print_lg("[Indeed] Stop requested. Halting run.")
                break
            self.search_and_apply_term(term, max_apps=switch_number)
            self.human_delay(2, 4)

        print_lg("\n=======================================================")
        print_lg(f"🏁 Indeed Applier Completed: {self.applied_count} Applied, {self.skipped_count} Skipped, {self.failed_count} Failed.")
        print_lg("=======================================================\n")
        self.close()

    def close(self):
        '''Safely close browser and resources.'''
        print_lg("[Indeed] Closing browser session...")
        try:
            if self.context:
                self.context.close()
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            pass
        if ai_client:
            try:
                close_ai_client(ai_client)
            except Exception:
                pass


if __name__ == "__main__":
    bot = IndeedBot()
    bot.run()
