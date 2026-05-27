"""One-shot backfill: populate constituencies.district and constituencies.region
from the same in-memory mapping that stats.py uses (geojson + DISTRICT_REGION
dict). After this runs, candidate_query.py can filter and group_by district /
region via plain SQL.

Idempotent: re-running is safe (it overwrites with the same values).
"""
import os
import sys

# Make sibling backend/ importable so we reuse stats._AC_DISTRICT and DISTRICT_REGION.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(os.path.dirname(HERE), "backend")
sys.path.insert(0, BACKEND)

from database import SessionLocal  # noqa: E402
from models import Constituency    # noqa: E402
import stats                       # noqa: E402

def main():
    stats._load_ac_district_map()
    updated = 0
    missing_district = 0
    missing_region = 0
    with SessionLocal() as db:
        for c in db.query(Constituency).all():
            district = stats._AC_DISTRICT.get(c.const_no)
            if not district:
                missing_district += 1
                continue
            district_title = district.title()
            region = stats.DISTRICT_REGION.get(district)
            if not region:
                missing_region += 1
            if c.district != district_title or c.region != region:
                c.district = district_title
                c.region = region
                updated += 1
        db.commit()
    print(f"updated={updated} missing_district={missing_district} missing_region={missing_region}")

if __name__ == "__main__":
    main()
