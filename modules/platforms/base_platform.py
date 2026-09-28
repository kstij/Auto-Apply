'''
Base Platform Interface for Multi-Platform Job Automation.
Defines the standard contract for platform-specific bot implementations (LinkedIn, Indeed, etc.).
'''

import os
import sys
import csv
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.helpers import print_lg


class BasePlatformBot(ABC):
    '''Abstract Base Class that all platform job applier engines must implement.'''

    def __init__(self, platform_name: str, config: Dict[str, Any] = None):
        self.platform_name = platform_name
        self.config = config or {}
        self.applied_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.is_running = False

    @abstractmethod
    def initialize_browser(self):
        '''Initialize the browser instance (Selenium / Playwright with anti-detection).'''
        pass

    @abstractmethod
    def login(self) -> bool:
        '''Log in to the platform or verify existing session state.'''
        pass

    def search_jobs(self) -> List[Dict[str, Any]]:
        '''Search for relevant job postings matching configured criteria.'''
        return []

    @abstractmethod
    def apply_to_job(self, job_data: Dict[str, Any]) -> bool:
        '''Navigate the application flow (Easy Apply / Indeed Apply) for a specific job.'''
        pass

    @abstractmethod
    def close(self):
        '''Clean up browser sessions and resources.'''
        pass

    def record_application(
        self,
        job_id: str,
        title: str,
        company: str,
        job_link: str,
        hr_name: str = "N/A",
        hr_link: str = "N/A",
        external_link: str = "N/A",
        history_csv: str = "all_applied_applications_history.csv"
    ):
        '''
        Record a successfully applied job into the unified application history CSV.
        Maintains backward compatibility with app.py history viewer while adding Platform column.
        '''
        history_dir = "all excels"
        os.makedirs(history_dir, exist_ok=True)
        csv_path = os.path.join(history_dir, history_csv)

        fieldnames = [
            "Job ID",
            "Title",
            "Company",
            "HR Name",
            "HR Link",
            "Job Link",
            "External Job link",
            "Date Applied",
            "Platform"
        ]

        file_exists = os.path.exists(csv_path)
        try:
            with open(csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    "Job ID": job_id,
                    "Title": title,
                    "Company": company,
                    "HR Name": hr_name,
                    "HR Link": hr_link,
                    "Job Link": job_link,
                    "External Job link": external_link,
                    "Date Applied": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Platform": self.platform_name
                })
            self.applied_count += 1
            print_lg(f"[{self.platform_name}] Recorded application #{self.applied_count} for '{title}' at '{company}'.")
        except Exception as e:
            print_lg(f"[{self.platform_name}] Error recording application to CSV: {e}")
