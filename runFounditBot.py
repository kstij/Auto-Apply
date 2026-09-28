'''
Direct CLI entry point for the Foundit (Monster) Job Applier.
'''

import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.platforms.foundit_engine import FounditBot

if __name__ == "__main__":
    bot = FounditBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\nStopping Foundit Bot...")
        bot.close()
        sys.exit(0)
