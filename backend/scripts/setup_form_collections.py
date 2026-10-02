"""Create the TPMS form collections ("tables") — one per form — with indexes.

Run once (safe to re-run; idempotent):
    cd backend && python -m scripts.setup_form_collections

Creates a dedicated collection for each of the four forms and provisions:
  • a UNIQUE compound index on (company_id, period, <respondent>) so a company +
    period + respondent has exactly one submission document, and
  • secondary indexes on company_id and period for reporting queries.

<respondent> is `hod_id` for the rating matrices (Accountability / Ownership /
Culture) and `md_id` for the Yes/No checklist (Implementation Feedback).

The same provisioning also runs automatically on app startup (see
app/db/mongodb.py); this script is for one-off/manual setup and verification.
"""
import sys

import certifi
from pymongo import ASCENDING, MongoClient

from app.config.settings import settings
from app.models.forms import FORM_COLLECTIONS, FORM_DEFINITIONS, KIND_YESNO_CHECKLIST


def _respondent_field(form_type: str) -> str:
    kind = (FORM_DEFINITIONS.get(form_type) or {}).get("kind")
    return "md_id" if kind == KIND_YESNO_CHECKLIST else "hod_id"


def main() -> int:
    client = MongoClient(settings.MONGODB_URI, tlsCAFile=certifi.where(),
                         serverSelectionTimeoutMS=60000, retryWrites=True)
    db = client[settings.DATABASE_NAME]
    existing_collections = set(db.list_collection_names())
    rc = 0

    for form_type, coll_name in FORM_COLLECTIONS.items():
        respondent = _respondent_field(form_type)
        try:
            if coll_name not in existing_collections:
                db.create_collection(coll_name)
                print(f"+ created collection '{coll_name}' ({form_type})")
            else:
                print(f"= collection '{coll_name}' already exists ({form_type})")

            coll = db[coll_name]
            coll.create_index(
                [("company_id", ASCENDING), ("period", ASCENDING), (respondent, ASCENDING)],
                unique=True, name="uniq_company_period_respondent",
            )
            coll.create_index([("company_id", ASCENDING)], name="by_company")
            coll.create_index([("period", ASCENDING)], name="by_period")
            print(f"  indexes ready on '{coll_name}' (unique: company_id+period+{respondent})")
        except Exception as e:
            print(f"! {coll_name}: failed to provision ({e})")
            rc = 1

    client.close()
    print("Done." if rc == 0 else "Completed with errors.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
