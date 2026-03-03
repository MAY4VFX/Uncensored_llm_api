import uuid
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def check_credits(db: AsyncSession, user_id: uuid.UUID, estimated_cost: float) -> bool:
    user = await db.get(User, user_id)
    if not user:
        return False
    return float(user.credits) >= estimated_cost


async def deduct_credits(db: AsyncSession, user_id: uuid.UUID, amount: float) -> bool:
    result = await db.execute(
        update(User)
        .where(User.id == user_id, User.credits >= Decimal(str(amount)))
        .values(credits=User.credits - Decimal(str(amount)))
    )
    await db.commit()
    return result.rowcount > 0


async def add_credits(db: AsyncSession, user_id: uuid.UUID, amount: float) -> None:
    await db.execute(
        update(User).where(User.id == user_id).values(credits=User.credits + Decimal(str(amount)))
    )
    await db.commit()
