import hashlib
import hmac
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.credits_service import add_credits

router = APIRouter(prefix="/billing", tags=["billing"])

# Credit packages: price_id → credits amount
CREDIT_PACKAGES = {
    "pri_credits_5": 5.0,
    "pri_credits_20": 20.0,
    "pri_credits_50": 50.0,
    "pri_credits_100": 100.0,
}

# Subscription tier mapping: price_id → (tier, monthly_credits)
SUBSCRIPTION_TIERS = {
    "pri_starter": ("starter", 5_000_000),
    "pri_pro": ("pro", 25_000_000),
    "pri_business": ("business", 100_000_000),
}


def _verify_paddle_signature(raw_body: bytes, signature: str) -> bool:
    """Verify Paddle webhook signature."""
    if not settings.paddle_webhook_secret:
        return True  # Skip verification in dev
    expected = hmac.new(settings.paddle_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def paddle_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Paddle webhook events."""
    raw_body = await request.body()
    signature = request.headers.get("Paddle-Signature", "")

    if not _verify_paddle_signature(raw_body, signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    data = await request.json()
    event_type = data.get("event_type", "")

    if event_type == "transaction.completed":
        await _handle_transaction_completed(data, db)
    elif event_type == "subscription.activated":
        await _handle_subscription_activated(data, db)
    elif event_type == "subscription.canceled":
        await _handle_subscription_canceled(data, db)

    return {"status": "ok"}


async def _handle_transaction_completed(data: dict, db: AsyncSession):
    """Handle one-time credit purchase."""
    transaction = data.get("data", {})
    custom_data = transaction.get("custom_data", {})
    user_id = custom_data.get("user_id")
    if not user_id:
        return

    items = transaction.get("items", [])
    for item in items:
        price_id = item.get("price", {}).get("id", "")
        credits = CREDIT_PACKAGES.get(price_id, 0)
        if credits > 0:
            await add_credits(db, uuid.UUID(user_id), credits)


async def _handle_subscription_activated(data: dict, db: AsyncSession):
    """Handle subscription activation — update tier."""
    subscription = data.get("data", {})
    custom_data = subscription.get("custom_data", {})
    user_id = custom_data.get("user_id")
    if not user_id:
        return

    items = subscription.get("items", [])
    for item in items:
        price_id = item.get("price", {}).get("id", "")
        tier_info = SUBSCRIPTION_TIERS.get(price_id)
        if tier_info:
            tier, monthly_credits = tier_info
            user = await db.get(User, uuid.UUID(user_id))
            if user:
                user.tier = tier
                await db.commit()


async def _handle_subscription_canceled(data: dict, db: AsyncSession):
    """Handle subscription cancellation — downgrade to free."""
    subscription = data.get("data", {})
    custom_data = subscription.get("custom_data", {})
    user_id = custom_data.get("user_id")
    if not user_id:
        return

    user = await db.get(User, uuid.UUID(user_id))
    if user:
        user.tier = "free"
        await db.commit()


@router.get("/packages")
async def list_packages():
    """List available credit packages and subscriptions."""
    return {
        "credit_packages": [
            {"price_id": k, "credits": v, "currency": "USD"}
            for k, v in CREDIT_PACKAGES.items()
        ],
        "subscriptions": [
            {"price_id": k, "tier": v[0], "monthly_token_limit": v[1]}
            for k, v in SUBSCRIPTION_TIERS.items()
        ],
    }
