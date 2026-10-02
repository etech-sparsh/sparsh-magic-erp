import motor.motor_asyncio
import certifi
from fastapi import HTTPException, status
from app.config.settings import settings

class Database:
    client: motor.motor_asyncio.AsyncIOMotorClient = None
    db = None

db_connection = Database()

async def connect_to_mongo():
    try:
        # Atlas (mongodb+srv) requires TLS; a typical local MongoDB instance does not.
        client_options = {
            "serverSelectionTimeoutMS": 20000,
            "connectTimeoutMS": 20000,
        }
        if settings.MONGODB_URI.startswith("mongodb+srv://"):
            client_options.update(tls=True, tlsCAFile=certifi.where())

        db_connection.client = motor.motor_asyncio.AsyncIOMotorClient(
            settings.MONGODB_URI,
            **client_options,
        )
        
        # Test connection with a ping
        await db_connection.client.admin.command('ping')
        
        # Select the database
        db_connection.db = db_connection.client[settings.DATABASE_NAME]
        
        # Create TTL index for password resets (10 minutes expiry)
        await db_connection.db["password_resets"].create_index("expires_at", expireAfterSeconds=0)

        # Provision the TPMS form collections (one "table" per form) with indexes.
        await _ensure_form_collections(db_connection.db)

        # Provision the TPMS core collections (activities, escalations, scores, …).
        await _ensure_tpms_collections(db_connection.db)

        # Provision the TPMS Leadership Score collections (all new; nothing existing touched).
        await _ensure_leadership_collections(db_connection.db)
        await _ensure_hrms_collections(db_connection.db)
        # Provision the IRM collections (weightage config + score snapshots).
        await _ensure_irm_collections(db_connection.db)

        print(f"[OK] Successfully connected to MongoDB (Database: {settings.DATABASE_NAME})")
        
    except Exception as e:
        print(f"[FAILED] connect to MongoDB: {e}")
        db_connection.db = None

async def _ensure_form_collections(db):
    """Idempotently create one collection ("table") per TPMS form with a unique
    (company_id, period, respondent) index + reporting indexes. The respondent is
    `md_id` for the Yes/No checklist and `hod_id` for the rating matrices. Failures
    here must never block startup, so they're logged and swallowed."""
    try:
        from app.models.forms import FORM_COLLECTIONS, FORM_DEFINITIONS, KIND_YESNO_CHECKLIST
        existing = set(await db.list_collection_names())
        for form_type, coll_name in FORM_COLLECTIONS.items():
            kind = (FORM_DEFINITIONS.get(form_type) or {}).get("kind")
            respondent = "md_id" if kind == KIND_YESNO_CHECKLIST else "hod_id"
            if coll_name not in existing:
                try:
                    await db.create_collection(coll_name)
                except Exception:
                    pass  # created concurrently or already present
            coll = db[coll_name]
            await coll.create_index(
                [("company_id", 1), ("period", 1), (respondent, 1)],
                unique=True, name="uniq_company_period_respondent",
            )
            await coll.create_index([("company_id", 1)], name="by_company")
            await coll.create_index([("period", 1)], name="by_period")
    except Exception as e:
        print(f"[WARN] Could not provision TPMS form collections: {e}")


async def _ensure_tpms_collections(db):
    """Idempotently create the TPMS core collections and their indexes from the single
    spec in app.models.tpms.TPMS_INDEXES, then seed the two master-data tables
    (activity catalogue + reminder rules) if they are empty.

    Seeding is insert-only and skipped once rows exist, so an operator's edits and the
    xlsx migration are never overwritten. As with the form collections, failures here
    must never block startup."""
    try:
        from app.models.tpms import (
            TPMS_INDEXES, ACTIVITY_SEED, REMINDER_RULE_SEED, DEPARTMENT_SEED,
            COLL_ACTIVITIES, COLL_REMINDER_RULES, COLL_DEPARTMENTS,
        )
        existing = set(await db.list_collection_names())
        for coll_name, keys, options in TPMS_INDEXES:
            if coll_name not in existing:
                try:
                    await db.create_collection(coll_name)
                    existing.add(coll_name)
                except Exception:
                    pass  # created concurrently or already present
            try:
                await db[coll_name].create_index(keys, **options)
            except Exception as ie:
                # An index conflicting with pre-existing data shouldn't kill startup.
                print(f"[WARN] TPMS index {options.get('name')} on {coll_name}: {ie}")

        # Seed master data only when the collection is completely empty.
        for coll_name, seed in ((COLL_ACTIVITIES, ACTIVITY_SEED),
                                (COLL_REMINDER_RULES, REMINDER_RULE_SEED),
                                (COLL_DEPARTMENTS, DEPARTMENT_SEED)):
            if await db[coll_name].count_documents({}) == 0 and seed:
                await db[coll_name].insert_many([dict(row) for row in seed])
                print(f"[OK] Seeded {coll_name} with {len(seed)} row(s)")
    except Exception as e:
        print(f"[WARN] Could not provision TPMS core collections: {e}")


async def _ensure_leadership_collections(db):
    """Idempotently create the TPMS Leadership Score collections and their indexes.

    Every collection in LEADERSHIP_INDEXES is new to this module, so no existing TPMS
    collection, document or index is read, altered or migrated here. The question master
    is NOT seeded at startup — it is seeded lazily on first use (insert-only, and skipped
    once any row exists), so an admin's edited questions are never overwritten. As with
    the two provisioners above, failures must never block startup."""
    try:
        from app.models.leadership import LEADERSHIP_INDEXES, LEADERSHIP_OBSOLETE_INDEXES
        existing = set(await db.list_collection_names())

        # Drop indexes an earlier build created that are now wrong. This removes an INDEX,
        # never a document — see LEADERSHIP_OBSOLETE_INDEXES for why each one has to go.
        # The response index in particular would reject every second response now that
        # responses carry no giver identity.
        for coll_name, index_name in LEADERSHIP_OBSOLETE_INDEXES:
            if coll_name not in existing:
                continue
            try:
                await db[coll_name].drop_index(index_name)
                print(f"[OK] Dropped obsolete index {index_name} on {coll_name}")
            except Exception:
                pass  # never created, or already gone
        for coll_name, keys, options in LEADERSHIP_INDEXES:
            if coll_name not in existing:
                try:
                    await db.create_collection(coll_name)
                    existing.add(coll_name)
                except Exception:
                    pass  # created concurrently or already present
            try:
                await db[coll_name].create_index(keys, **options)
            except Exception as ie:
                print(f"[WARN] Leadership index {options.get('name')} on {coll_name}: {ie}")
    except Exception as e:
        print(f"[WARN] Could not provision TPMS Leadership Score collections: {e}")


async def _ensure_hrms_collections(db):
    """Idempotently create the HRMS collections and their indexes from the single spec in
    app.models.hrms.HRMS_INDEXES.

    Deliberately mirrors _ensure_tpms_collections above, with one difference: HRMS seeds no
    master data at startup. Its reference data (departments, designations, settings) is
    company-scoped and created when a company is onboarded onto the module, so there is
    nothing global to seed.

    As with the TPMS/forms provisioners, failures here must never block startup — a bad
    index should degrade the module, not take the whole ERP down."""
    try:
        from app.models.hrms import HRMS_INDEXES
        existing = set(await db.list_collection_names())
        for coll_name, keys, options in HRMS_INDEXES:
            if coll_name not in existing:
                try:
                    await db.create_collection(coll_name)
                    existing.add(coll_name)
                except Exception:
                    pass  # created concurrently or already present
            try:
                await db[coll_name].create_index(keys, **options)
            except Exception as ie:
                # MongoDB does NOT alter an existing index when its definition changes -- it
                # refuses and leaves the old one in place. Swallowing that would make this
                # provisioner a liar: the spec says one thing and the database does another,
                # silently, forever.
                #
                # This is not hypothetical. Phase 9 made `uniq_user` sparse so that several
                # onboarding-created employees (who have no `user_id` key at all) can
                # coexist. Under the old non-sparse index Mongo treats a missing field as
                # null, so the SECOND such employee at any company would fail with a
                # duplicate-key error. Reconciling by name fixes those already deployed.
                #
                # TWO codes matter, and matching only one is how this fix failed the first
                # time (Phase 10 Finding #1). Atlas raised 86, not 85:
                #   85 IndexOptionsConflict  - same keys and name, different options
                #   86 IndexKeySpecsConflict - same name, different keys or spec
                # Both mean "the deployed index does not match the spec", which is exactly
                # the case to reconcile. Matched on the numeric codes alone -- the message
                # wording is not a stable contract, and the earlier attempt relied on it.
                #
                # Anything else (a genuine duplicate in the data, say) is still only
                # reported, and nothing here blocks startup.
                name = options.get("name")
                conflict = getattr(ie, "code", None) in (85, 86)
                if not (conflict and name and name != "_id_"):
                    print(f"[WARN] HRMS index {name} on {coll_name}: {ie}")
                    continue
                try:
                    await db[coll_name].drop_index(name)
                    await db[coll_name].create_index(keys, **options)
                    print(f"[INFO] HRMS index {name} on {coll_name} rebuilt to match the spec")
                except Exception as re_ie:
                    print(f"[WARN] HRMS index {name} on {coll_name} could not be "
                          f"reconciled: {re_ie}")
    except Exception as e:
        print(f"[WARN] Could not provision HRMS collections: {e}")


async def close_mongo_connection():
    if db_connection.client:
        db_connection.client.close()
        print("Closed MongoDB connection")

async def _ensure_irm_collections(db):
    """Idempotently create the IRM collections and their indexes. No seeding: a company
    with no `irm_configs` row simply reads the registry defaults, so the first save is
    what creates the row. As elsewhere, failures here must never block startup."""
    try:
        from app.models.irm import IRM_INDEXES
        existing = set(await db.list_collection_names())
        for coll_name, keys, options in IRM_INDEXES:
            if coll_name not in existing:
                try:
                    await db.create_collection(coll_name)
                    existing.add(coll_name)
                except Exception:
                    pass  # created concurrently or already present
            try:
                await db[coll_name].create_index(keys, **options)
            except Exception as ie:
                print(f"[WARN] IRM index {options.get('name')} on {coll_name}: {ie}")
    except Exception as e:
        print(f"[WARN] Could not provision IRM collections: {e}")


def get_db():
    if db_connection.db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is not available. Check that MongoDB is running and that MONGODB_URI is correct."
        )
    return db_connection.db

def get_collection(name: str):
    db = get_db()
    return db[name]
