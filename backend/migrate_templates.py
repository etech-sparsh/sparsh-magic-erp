import asyncio
import os
import sys
from datetime import datetime

# Adjust path to import app modules
sys.path.append(os.getcwd())

from app.db.mongodb import connect_to_mongo, get_collection

async def migrate_templates():
    await connect_to_mongo()
    col = get_collection("notification_templates")
    
    # Update all existing templates to have scope: 'staff' if they don't have a scope
    result = await col.update_many(
        {"scope": {"$exists": False}},
        {"$set": {"scope": "staff"}}
    )
    print(f"Updated {result.modified_count} templates to 'staff' scope.")
    
    # Ensure they have 'is_active': True
    await col.update_many(
        {"is_active": {"$exists": False}},
        {"$set": {"is_active": True}}
    )

if __name__ == "__main__":
    asyncio.run(migrate_templates())
