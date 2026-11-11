"""Allow running protas with ``python -m protas``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
