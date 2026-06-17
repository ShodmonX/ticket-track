import asyncio
from sqlalchemy import select
from shared.database import async_session
from shared.models import Subscription

async def main():
    async with async_session() as session:
        stmt = select(Subscription)
        result = await session.execute(stmt)
        subs = result.scalars().all()
        print(f"Total active subscriptions: {len(subs)}")
        for s in subs:
            print(f"Route: {s.origin_name} -> {s.destination_name}, Date: {s.date}, Transport: {s.transport_type}, Active: {s.is_active}")

if __name__ == "__main__":
    asyncio.run(main())
