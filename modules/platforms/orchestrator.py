'''
Multi-Platform Job Application Orchestrator.
Allows running LinkedIn, Indeed, or All platforms sequentially or in parallel.
'''

import os
import sys

# Ensure project root is in sys.path when script is run directly or as a subprocess
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import argparse
from modules.helpers import print_lg


def run_linkedin():
    print_lg("\n=======================================================")
    print_lg("         🔵 LAUNCHING LINKEDIN AUTO APPLIER")
    print_lg("=======================================================\n")
    import runAiBot
    if hasattr(runAiBot, "main"):
        runAiBot.main()


def run_indeed():
    print_lg("\n=======================================================")
    print_lg("         🟣 LAUNCHING INDEED AUTO APPLIER")
    print_lg("=======================================================\n")
    from modules.platforms.indeed_engine import IndeedBot
    bot = IndeedBot()
    bot.run()


def run_glassdoor():
    print_lg("\n=======================================================")
    print_lg("         🟢 LAUNCHING GLASSDOOR AUTO APPLIER")
    print_lg("=======================================================\n")
    from modules.platforms.glassdoor_engine import GlassdoorBot
    bot = GlassdoorBot()
    bot.run()


def run_foundit():
    print_lg("\n=======================================================")
    print_lg("         🟡 LAUNCHING FOUNDIT (MONSTER) AUTO APPLIER")
    print_lg("=======================================================\n")
    from modules.platforms.foundit_engine import FounditBot
    bot = FounditBot()
    bot.run()


def main():
    parser = argparse.ArgumentParser(description="Multi-Platform Auto Job Applier Orchestrator")
    parser.add_argument(
        "--platform",
        choices=["linkedin", "indeed", "glassdoor", "foundit", "all"],
        default="linkedin",
        help="Target platform to run job applications on"
    )
    args = parser.parse_args()

    print_lg(f"[Orchestrator] Starting job application process for platform: '{args.platform.upper()}'")

    if args.platform == "linkedin":
        run_linkedin()
    elif args.platform == "indeed":
        run_indeed()
    elif args.platform == "glassdoor":
        run_glassdoor()
    elif args.platform == "foundit":
        run_foundit()
    elif args.platform == "all":
        print_lg("[Orchestrator] Executing multi-platform run (LinkedIn, Indeed, Glassdoor, Foundit)...")
        for runner, name in [
            (run_linkedin, "LinkedIn"),
            (run_indeed, "Indeed"),
            (run_glassdoor, "Glassdoor"),
            (run_foundit, "Foundit")
        ]:
            try:
                runner()
            except Exception as e:
                print_lg(f"[Orchestrator] {name} run encountered error: {e}")

    print_lg("[Orchestrator] All requested platform tasks completed.")


if __name__ == "__main__":
    main()
