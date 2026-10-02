import asyncio
import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.db.mongodb import connect_to_mongo
from backend.app.scripts.seed_templates import seed_notification_templates

async def main():
    await connect_to_mongo()
    await seed_notification_templates()
    print("Seeding complete.")

if __name__ == "__main__":
    asyncio.run(main())
