"""
Seed script: creates the orders table and inserts sample data.
Run inside the container: docker-compose exec sample_app python seed.py
"""

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@postgres:5432/incidents",
)

SAMPLE_ORDERS = [
    ("Alice Johnson", "completed", 249.99),
    ("Bob Smith", "pending", 89.50),
    ("Carol White", "shipped", 1200.00),
    ("David Brown", "completed", 34.75),
    ("Eve Davis", "cancelled", 560.00),
    ("Frank Miller", "pending", 75.25),
    ("Grace Wilson", "completed", 430.00),
    ("Henry Moore", "processing", 195.60),
    ("Irene Taylor", "shipped", 88.00),
    ("Jack Anderson", "completed", 3200.50),
]


async def seed() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS orders (
                    id          SERIAL PRIMARY KEY,
                    customer_name VARCHAR(255) NOT NULL,
                    status      VARCHAR(50)  NOT NULL,
                    amount      NUMERIC(10, 2) NOT NULL
                )
            """)
        )
        print("Table 'orders' ready.")

        await conn.execute(text("TRUNCATE TABLE orders RESTART IDENTITY"))

        await conn.execute(
            text(
                "INSERT INTO orders (customer_name, status, amount) "
                "VALUES (:customer_name, :status, :amount)"
            ),
            [
                {"customer_name": name, "status": status, "amount": amount}
                for name, status, amount in SAMPLE_ORDERS
            ],
        )

        print(f"Seeded {len(SAMPLE_ORDERS)} orders into 'orders'.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
