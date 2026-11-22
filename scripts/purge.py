"""Purge person-level data past the retention period (ops_config.json person_raw_retention_days, PROPOSED 0 days).
    python scripts/purge.py [--db clearance.db] [--older-than-days N]
Keeps only hashes and results; see clearance/retention.py."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clearance import retention

if __name__ == "__main__": raise SystemExit(retention.main())
