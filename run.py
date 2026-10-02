"""Generate illustrated storybooks. Usage: python run.py [--help]"""

import sys
from pathlib import Path

from src.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], project_dir=Path(__file__).resolve().parent))
