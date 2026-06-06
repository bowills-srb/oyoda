"""
stripe_billing.py — Stripe Billing Integration for Oyvoda

Handles the full operator billing lifecycle:
  1. Operator signup → create Stripe Customer
  2. Activate subscription → create Stripe Subscription
  3. Usage reporting → report active unit count monthly
  4. Webhook handler → invoice.paid, payment_failed, subscription.deleted
  5. Billing portal → hosted Stripe portal for operators to manage their card

Pricing model:
  - Base: $299/month per operator (up to 10 units)
  - Per unit above 10: $15/unit/month (metered)
  - Annual discount: 2 months free (billed as 10x monthly rate)

Environment variables required in Railway:
  STRIPE_SECRET_KEY      — sk_live_... (from Stripe Dashboard → API Keys)
  STRIPE_PUBLISHABLE_KEY — pk_live_... (shown on frontend for Stripe.js)
  STRIPE_WEBHOOK_SECRET  — whsec_... (from Stripe Dashboard → Webhooks)
  STRIPE_PRICE_ID_BASE   — price_... (create in Stripe Dashboard → Products)
  STRIPE_PRICE_ID_UNIT   — price_... (metered price for per-unit overage)

Setup steps:
  1. Create Stripe account at stripe.com
  2. Create Product "Oyvoda Operator Plan" in Stripe Dashboard
  3. Add Price: $299/month recurring → copy Price ID → STRIPE_PRICE_ID_BASE
  4. Add Price: $15/unit/month metered → copy Price ID → STRIPE_PRICE_ID_UNIT
  5. Create Webhook endpoint in Stripe Dashboard:
     URL: https://oyvoda-production.up.railway.app/api/v1/billing/webhook
     Events: invoice.paid, invoice.payment_failed, customer.subscription.deleted,
             customer.subscription.updated
  6. Copy webhook signing secret → STRIPE_WEBHOOK_SECRET
  7. Set all env vars in Railway

PCI-DSS note:
  Oyvoda NEVER handles raw card data. All card collection is done via
  Stripe Checkout or the Stripe Billing Portal — card data goes directly
  from the browser to Stripe's servers. Oyvoda only stores the Stripe
  Customer ID and Subscription ID. This keeps Oyvoda in SAQ A scope
  (lowest PCI-DSS compliance tier).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])

# ─── Config ──────────────────────────────────────────────────────────────────

STRIPE_SECRET_KEY      = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID_BASE   = os.getenv("STRIPE_PRICE_ID_BASE", "")    # $299/mo flat
STRIPE_PRICE_ID_UNIT   = os.getenv("STRIPE_PRICE_ID_UNIT", "")    # $15/unit metered

STRIPE_API_BASE = "https://api.stripe.com/v1"


def _stripe_enabled() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_SECRET_KEY.startswith("sk_"))


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": "2024-06-20",
    }


# ─── Stripe API helpers ───────────────────────────────────────────────────────

async def _stripe_post(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """POST to Stripe API with form-encoded data."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{STRIPE_API_BASE}/{path}",
            headers=_headers(),
            data=data,
        )
    result = resp.json()
    if resp.status_code >= 400:
        logger.error(f"[Stripe] {path} failed: {result}")
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Stripe error: {result.get('error', {}).get('message', 'Unknown error')}"
        )
    return result


async def _stripe_get(path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """GET from Stripe API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{STRIPE_API_BASE}/{path}",
            headers=_headers(),
            params=params or {},
        )
    result = resp.json()
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Stripe error: {result.get('error', {}).get('message', 'Unknown error')}"
        )
    return result


# ─── Customer management ─────────────────────────────────────────────────────

async def create_stripe_customer(
    operator_id: str,
    email: str,
    name: str,
    company: str,
) -> str:
    """
    Create a Stripe Customer for a new operator.
    Returns the Stripe Customer ID (cus_...).
    Store this in your operators table as stripe_customer_id.
    """
    result = await _stripe_post("customers", {
        "email": email,
        "name": name,
        "description": f"Oyvoda operator: {company}",
        "metadata[operator_id]": operator_id,
        "metadata[company]": company,
    })
    customer_id = result["id"]
    logger.info(f"[Stripe] Created customer {customer_id} for operator {operator_id}")
    return customer_id


async def get_or_create_customer(
    operator_id: str,
    email: str,
    name: str,
    company: str,
) -> str:
    """Get existing Stripe customer by email, or create one."""
    # Search for existing customer
    result = await _stripe_get("customers/search", {
        "query": f"email:'{email}' AND metadata['operator_id']:'{operator_id}'"
    })
    customers = result.get("data", [])
    if customers:
        return customers[0]["id"]
    return await create_stripe_customer(operator_id, email, name, company)


# ─── Subscription management ─────────────────────────────────────────────────

async def create_subscription(
    customer_id: str,
    operator_id: str,
    unit_count: int = 0,
    trial_days: int = 14,
) -> Dict[str, Any]:
    """
    Create a Stripe Subscription for an operator.

    Returns subscription dict with:
      - id: subscription ID (sub_...)
      - status: "trialing" | "active" | "past_due"
      - client_secret: for Stripe.js payment confirmation (if needed)
      - latest_invoice.payment_intent.client_secret: for 3DS confirmation
    """
    if not STRIPE_PRICE_ID_BASE:
        raise HTTPException(500, "STRIPE_PRICE_ID_BASE not configured in Railway")

    # Build subscription items
    items = [{"price": STRIPE_PRICE_ID_BASE}]

    # Add metered unit price if configured and operator has >10 units
    if STRIPE_PRICE_ID_UNIT and unit_count > 10:
        items.append({
            "price": STRIPE_PRICE_ID_UNIT,
            "quantity": unit_count - 10,  # Overage units
        })

    data: Dict[str, Any] = {
        "customer": customer_id,
        "payment_behavior": "default_incomplete",
        "payment_settings[save_default_payment_method]": "on_subscription",
        "expand[]": "latest_invoice.payment_intent",
        "metadata[operator_id]": operator_id,
        "metadata[unit_count]": str(unit_count),
    }

    # Add items
    for i, item in enumerate(items):
        for k, v in item.items():
            data[f"items[{i}][{k}]"] = v

    # Trial period
    if trial_days > 0:
        data["trial_period_days"] = str(trial_days)

    result = await _stripe_post("subscriptions", data)
    logger.info(f"[Stripe] Created subscription {result['id']} for customer {customer_id}")
    return result


async def update_unit_count(
    subscription_id: str,
    new_unit_count: int,
) -> Dict[str, Any]:
    """
    Update the metered unit count on an existing subscription.
    Call this monthly or when the operator adds/removes properties.
    """
    if not STRIPE_PRICE_ID_UNIT:
        return {}

    # Get current subscription to find the unit price item
    sub = await _stripe_get(f"subscriptions/{subscription_id}")
    unit_item_id = None
    for item in sub.get("items", {}).get("data", []):
        if item.get("price", {}).get("id") == STRIPE_PRICE_ID_UNIT:
            unit_item_id = item["id"]
            break

    overage = max(0, new_unit_count - 10)

    if unit_item_id:
        # Update existing unit item
        result = await _stripe_post(
            f"subscription_items/{unit_item_id}",
            {"quantity": str(overage)}
        )
    elif overage > 0:
        # Add unit item (operator just exceeded 10 units)
        result = await _stripe_post(
            f"subscriptions/{subscription_id}",
            {
                "items[0][price]": STRIPE_PRICE_ID_UNIT,
                "items[0][quantity]": str(overage),
            }
        )
    else:
        result = {}

    logger.info(f"[Stripe] Updated subscription {subscription_id}: {new_unit_count} units ({overage} overage)")
    return result


async def cancel_subscription(
    subscription_id: str,
    at_period_end: bool = True,
) -> Dict[str, Any]:
    """
    Cancel a subscription. Default: cancel at period end (not immediately).
    PCI-DSS: log all cancellation events via security_layer.audit.log_payment().
    """
    if at_period_end:
        result = await _stripe_post(
            f"subscriptions/{subscription_id}",
            {"cancel_at_period_end": "true"}
        )
    else:
        # Immediate cancellation — refund prorated amount if needed
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{STRIPE_API_BASE}/subscriptions/{subscription_id}",
                headers=_headers(),
            )
        result = resp.json()

    logger.info(f"[Stripe] Cancelled subscription {subscription_id} (at_period_end={at_period_end})")
    return result


# ─── Billing portal ──────────────────────────────────────────────────────────

async def create_billing_portal_session(
    customer_id: str,
    return_url: str,
) -> str:
    """
    Create a Stripe Billing Portal session.
    Returns the URL to redirect the operator to.
    They can manage their payment method, download invoices, cancel, etc.
    Operators never need to call Oyvoda support for billing issues.
    """
    result = await _stripe_post("billing_portal/sessions", {
        "customer": customer_id,
        "return_url": return_url,
    })
    return result["url"]


async def create_checkout_session(
    customer_id: str,
    operator_id: str,
    success_url: str,
    cancel_url: str,
    unit_count: int = 0,
    trial_days: int = 14,
) -> str:
    """
    Create a Stripe Checkout session for initial payment collection.
    Returns the Checkout URL to redirect the operator to.

    Stripe Checkout handles all PCI compliance — card data never touches Oyvoda.
    """
    if not STRIPE_PRICE_ID_BASE:
        raise HTTPException(500, "STRIPE_PRICE_ID_BASE not configured in Railway")

    data: Dict[str, Any] = {
        "customer": customer_id,
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata[operator_id]": operator_id,
        "subscription_data[metadata][operator_id]": operator_id,
        "subscription_data[trial_period_days]": str(trial_days),
        "line_items[0][price]": STRIPE_PRICE_ID_BASE,
        "line_items[0][quantity]": "1",
        # Collect billing address for tax purposes
        "billing_address_collection": "required",
        # Allow promotion codes
        "allow_promotion_codes": "true",
    }

    if STRIPE_PRICE_ID_UNIT and unit_count > 10:
        overage = unit_count - 10
        data["line_items[1][price]"] = STRIPE_PRICE_ID_UNIT
        data["line_items[1][quantity]"] = str(overage)

    result = await _stripe_post("checkout/sessions", data)
    return result["url"]


# ─── Invoice helpers ─────────────────────────────────────────────────────────

async def get_invoices(
    customer_id: str,
    limit: int = 12,
) -> list:
    """Get recent invoices for an operator (for dashboard billing tab)."""
    result = await _stripe_get("invoices", {
        "customer": customer_id,
        "limit": str(limit),
        "expand[]": "data.payment_intent",
    })
    return result.get("data", [])


async def get_subscription(subscription_id: str) -> Dict[str, Any]:
    """Get current subscription details."""
    return await _stripe_get(f"subscriptions/{subscription_id}", {
        "expand[]": "latest_invoice",
    })


# ─── Webhook handler ─────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """
    Stripe webhook endpoint.
    Verifies signature, processes events.

    Configure in Stripe Dashboard → Webhooks:
    URL: https://oyvoda-production.up.railway.app/api/v1/billing/webhook
    Events: invoice.paid, invoice.payment_failed,
            customer.subscription.deleted, customer.subscription.updated
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "STRIPE_WEBHOOK_SECRET not configured")

    # Read raw body for signature verification
    body = await request.body()

    # Verify Stripe signature (prevents spoofed webhooks)
    event = _verify_webhook_signature(body, stripe_signature or "", STRIPE_WEBHOOK_SECRET)
    if not event:
        raise HTTPException(400, "Invalid webhook signature")

    event_type = event.get("type", "")
    event_data = event.get("data", {}).get("object", {})

    logger.info(f"[Stripe Webhook] {event_type}")

    # Log to security audit trail (PCI-DSS Requirement 10)
    try:
        from app.core.security_layer import security, AuditEventType
        operator_id = event_data.get("metadata", {}).get("operator_id", "unknown")
        security.audit.log(
            event_type=AuditEventType.PAYMENT_COMPLETED if "paid" in event_type
                       else AuditEventType.PAYMENT_FAILED if "failed" in event_type
                       else AuditEventType.PAYMENT_INITIATED,
            actor_id=operator_id,
            action=event_type,
            resource_id=event_data.get("id", ""),
            success="paid" in event_type or "succeeded" in event_type,
            metadata={
                "stripe_event_id": event.get("id"),
                "event_type": event_type,
                "amount": event_data.get("amount_paid") or event_data.get("amount"),
                "currency": event_data.get("currency"),
                "pci_audit": True,
            }
        )
    except Exception as e:
        logger.warning(f"[Stripe Webhook] Audit log failed (non-fatal): {e}")

    # Handle specific events
    if event_type == "invoice.paid":
        await _handle_invoice_paid(event_data)

    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(event_data)

    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_cancelled(event_data)

    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(event_data)

    return JSONResponse({"received": True})


async def _handle_invoice_paid(invoice: Dict[str, Any]) -> None:
    """Operator successfully paid — ensure account is active."""
    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")
    amount = invoice.get("amount_paid", 0) / 100  # Convert cents to dollars

    logger.info(
        f"[Stripe] Invoice paid: customer={customer_id}, "
        f"subscription={subscription_id}, amount=${amount:.2f}"
    )

    # TODO: Update operator status to 'active' in DB
    # await db_set_operator_active(customer_id, subscription_id)


async def _handle_payment_failed(invoice: Dict[str, Any]) -> None:
    """Payment failed — notify operator, consider grace period."""
    customer_id = invoice.get("customer")
    attempt_count = invoice.get("attempt_count", 0)
    next_attempt = invoice.get("next_payment_attempt")

    logger.warning(
        f"[Stripe] Payment failed: customer={customer_id}, "
        f"attempt={attempt_count}, next_attempt={next_attempt}"
    )

    # Stripe's Smart Retries handles automatic retries
    # After 4 failures, subscription goes to 'past_due' then 'unpaid'
    # TODO: Send email via SendGrid notifying operator of failed payment
    # TODO: After final failure, set operator status to 'suspended' in DB


async def _handle_subscription_cancelled(subscription: Dict[str, Any]) -> None:
    """Subscription cancelled — deactivate operator account."""
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")
    cancelled_at = subscription.get("canceled_at")

    logger.info(
        f"[Stripe] Subscription cancelled: customer={customer_id}, "
        f"subscription={subscription_id}, cancelled_at={cancelled_at}"
    )

    # TODO: Set operator status to 'cancelled' in DB
    # TODO: Send offboarding email


async def _handle_subscription_updated(subscription: Dict[str, Any]) -> None:
    """Subscription updated (plan change, unit count change, etc.)."""
    subscription_id = subscription.get("id")
    status = subscription.get("status")
    logger.info(f"[Stripe] Subscription updated: {subscription_id}, status={status}")

    # TODO: Sync subscription status to operator record in DB


def _verify_webhook_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
) -> Optional[Dict[str, Any]]:
    """
    Verify Stripe webhook signature using HMAC-SHA256.
    This prevents spoofed webhooks from malicious actors.
    Reference: https://stripe.com/docs/webhooks/signatures
    """
    import hashlib
    import hmac
    import json
    import time

    try:
        # Parse signature header: t=timestamp,v1=signature
        parts = dict(item.split("=", 1) for item in signature_header.split(",") if "=" in item)
        timestamp = parts.get("t", "")
        signature = parts.get("v1", "")

        if not timestamp or not signature:
            return None

        # Reject events older than 5 minutes (replay attack prevention)
        event_time = int(timestamp)
        if abs(time.time() - event_time) > 300:
            logger.warning("[Stripe] Webhook timestamp too old — possible replay attack")
            return None

        # Compute expected signature
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(expected, signature):
            logger.warning("[Stripe] Webhook signature mismatch")
            return None

        return json.loads(payload)

    except Exception as e:
        logger.error(f"[Stripe] Webhook verification error: {e}")
        return None


# ─── API endpoints ────────────────────────────────────────────────────────────

@router.get("/status")
async def billing_status(request: Request):
    """
    Get billing status for the authenticated operator.
    Called by the dashboard billing tab.
    """
    user = request.cookies.get("oyvoda_access")
    if not user:
        raise HTTPException(401, "Not authenticated")

    if not _stripe_enabled():
        return {
            "enabled": False,
            "message": "Billing not configured — set STRIPE_SECRET_KEY in Railway",
        }

    # TODO: Look up operator's stripe_customer_id and stripe_subscription_id from DB
    # For now return placeholder
    return {
        "enabled": True,
        "publishable_key": STRIPE_PUBLISHABLE_KEY,
        "status": "active",
        "plan": "Oyvoda Operator Plan",
        "amount": 299.00,
        "currency": "usd",
        "billing_cycle": "monthly",
        "next_payment": None,
        "trial_active": False,
    }


@router.post("/create-checkout")
async def create_checkout(request: Request):
    """
    Create a Stripe Checkout session for a new operator signup.
    Redirects to Stripe-hosted checkout page.
    PCI-DSS: card data never touches Oyvoda servers.
    """
    if not _stripe_enabled():
        raise HTTPException(503, "Billing not configured")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body")

    operator_id = data.get("operator_id", "")
    email = data.get("email", "")
    name = data.get("name", "")
    company = data.get("company", "")
    unit_count = int(data.get("unit_count", 0))

    if not all([operator_id, email, name]):
        raise HTTPException(400, "operator_id, email, and name are required")

    # Get or create Stripe customer
    customer_id = await get_or_create_customer(operator_id, email, name, company)

    base_url = os.getenv("BASE_URL", "https://oyvoda-production.up.railway.app")
    checkout_url = await create_checkout_session(
        customer_id=customer_id,
        operator_id=operator_id,
        success_url=f"{base_url}/app/dashboard?billing=success",
        cancel_url=f"{base_url}/app/dashboard?billing=cancelled",
        unit_count=unit_count,
        trial_days=14,
    )

    return JSONResponse({"checkout_url": checkout_url})


@router.get("/portal")
async def billing_portal(request: Request):
    """
    Redirect operator to Stripe Billing Portal.
    They can update payment method, download invoices, cancel subscription.
    """
    if not _stripe_enabled():
        raise HTTPException(503, "Billing not configured")

    # TODO: Get stripe_customer_id from DB using authenticated operator
    # For now, raise helpful error
    raise HTTPException(501, "Connect operator to Stripe customer first")


@router.get("/invoices")
async def list_invoices(request: Request):
    """Get invoice history for the authenticated operator."""
    if not _stripe_enabled():
        return {"invoices": [], "message": "Billing not configured"}

    # TODO: Get stripe_customer_id from DB
    return {"invoices": [], "message": "No invoices yet"}


@router.get("/config")
async def billing_config():
    """Return Stripe publishable key for frontend Stripe.js initialization."""
    return {
        "publishable_key": STRIPE_PUBLISHABLE_KEY if _stripe_enabled() else None,
        "enabled": _stripe_enabled(),
    }
