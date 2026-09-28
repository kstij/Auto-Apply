'''
Direct CLI entry point for the Indeed Job Applier.
'''

import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.platforms.indeed_engine import IndeedBot

if __name__ == "__main__":
    bot = IndeedBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\nStopping Indeed Bot...")
        bot.close()
        sys.exit(0)
