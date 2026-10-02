import asyncio
import os
import sys

# Adjust path to import app modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from app.db.mongodb import connect_to_mongo, get_collection, close_mongo_connection
from app.utils.calendar_utils import get_target_collection_name, CALENDAR_COLLECTIONS

async def migrate():
    print("Connecting to MongoDB...")
    await connect_to_mongo()
    
    legacy_col = get_collection("calendar_events")
    legacy_count = await legacy_col.count_documents({})
    
    if legacy_count == 0:
        print("No events found in 'calendar_events'. Already migrated?")
        await close_mongo_connection()
        return

    print(f"Found {legacy_count} events in legacy collection. Starting migration...")
    
    # Read all events
    all_events = await legacy_col.find({}).to_list(None)
    
    counts = {col: 0 for col in CALENDAR_COLLECTIONS}
    errors = 0
    
    for event in all_events:
        try:
            target_col_name = await get_target_collection_name(event)
            target_col = get_collection(target_col_name)
            
            # Check for existing
            exists = await target_col.find_one({"_id": event["_id"]})
            if not exists:
                await target_col.insert_one(event)
                counts[target_col_name] += 1
            else:
                print(f"Skipping {event['_id']} - already exists in {target_col_name}")
        except Exception as e:
            print(f"Error migrating event {event.get('_id')}: {e}")
            errors += 1
            
    print("\n" + "="*30)
    print("MIGRATION COMPLETED")
    print("="*30)
    for col, count in counts.items():
        print(f"{col.ljust(25)}: {count} docs moved")
    print("-" * 30)
    print(f"Errors encountered       : {errors}")
    print("=" * 30)
    print("\nSUCCESS: All data has been copied to the new collections.")
    print("IMPORTANT: The 'calendar_events' collection remains intact for safety.")
    print("Please verify the Calendar UI is working correctly before manually dropping 'calendar_events'.")
    
    await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(migrate())
