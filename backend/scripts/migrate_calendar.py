import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# Update with your MongoDB connection string
MONGO_URI = "mongodb://localhost:27017"
DATABASE_NAME = "sparsh_erp"

async def migrate_calendar_collections():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DATABASE_NAME]
    
    mapping = {
        "STAFF_CALENDER_EVENTS": "STAFF_CALENDER",
        "STAFF_CALENDER_TASKS": "STAFF_CALENDER",
        "LEARNER_CALENDER_EVENTS": "LEARNER_CALENDER",
        "LEARNER_CALENDER_TASKS": "LEARNER_CALENDER"
    }
    
    print("--- Starting Calendar Migration ---")
    
    for old_name, new_name in mapping.items():
        old_col = db[old_name]
        new_col = db[new_name]
        
        docs = await old_col.find({}).to_list(None)
        if not docs:
            print(f"Skipping {old_name} (Empty)")
            continue
            
        print(f"Migrating {len(docs)} documents from {old_name} to {new_name}...")
        
        # Insert into new collection
        try:
            await new_col.insert_many(docs)
            print(f"Successfully moved records from {old_name}.")
            # Optional: Delete old collection records after verification
            # await old_col.drop() 
        except Exception as e:
            print(f"Error migrating {old_name}: {e}")

    print("--- Migration Complete ---")
    client.close()

if __name__ == "__main__":
    asyncio.run(migrate_calendar_collections())
