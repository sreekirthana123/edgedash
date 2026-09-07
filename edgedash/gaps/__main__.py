"""CLI entry point for gaps module.

Usage:
    python -m edgedash.gaps          # Show latest snapshot
    python -m edgedash.gaps --trend  # Show trend across snapshots
"""

import sys
from edgedash.config import Config
from edgedash.gaps import print_gaps_table, print_gaps_trend


if __name__ == "__main__":
    config = Config.load()
    
    if "--trend" in sys.argv:
        print_gaps_trend(config)
    else:
        print_gaps_table(config)
