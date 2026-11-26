"""Twilio telephony helpers: signature verification, TwiML, and outbound calls."""

import base64
import hashlib
import hmac
import logging
from typing import Any
from xml.sax.saxutils import escape

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class TelephonyError(Exception):
    """Raised when Twilio configuration or API call fails."""


def mask_phone(phone: str | None) -> str:
    """Mask a phone number before logging."""
    if not phone:
        return "unknown"
    digits = phone.strip()
    if len(digits) <= 4:
        return "****"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def verify_twilio_signature(url: str, params: dict[str, str], signature: str | None) -> bool:
    """Verify X-Twilio-Signature using HMAC-SHA1 per Twilio's webhook spec."""
    if not settings.twilio_auth_token:
        return True
    if not signature:
        return False

    data = url + "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    digest = hmac.new(
        settings.twilio_auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def build_stream_twiml(ws_url: str, tenant_id: int, language: str = "en") -> str:
    """Build TwiML that connects the call to our Media Streams WebSocket."""
    safe_url = escape(ws_url)
    safe_lang = escape(language)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<Stream url="{safe_url}">'
        f'<Parameter name="tenant_id" value="{tenant_id}" />'
        f'<Parameter name="language" value="{safe_lang}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )


async def initiate_outbound_call(to_number: str, tenant_id: int, language: str = "en") -> dict[str, Any]:
    """Trigger an outbound Twilio call bridged to /twilio/voice."""
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_phone_number):
        raise TelephonyError("Twilio credentials (SID, auth token, phone number) are not configured in .env")

    base = settings.public_base_url.rstrip("/")
    twiml_url = f"{base}/twilio/voice?tenant_id={tenant_id}&language={language}"
    status_url = f"{base}/twilio/status?tenant_id={tenant_id}"
    api_url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Calls.json"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                api_url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                data={
                    "To": to_number,
                    "From": settings.twilio_phone_number,
                    "Url": twiml_url,
                    "StatusCallback": status_url,
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("Twilio outbound request failed: %s", type(exc).__name__)
        raise TelephonyError("Unable to reach Twilio API.") from exc

    if resp.status_code >= 400:
        logger.warning("Twilio outbound API returned %s", resp.status_code)
        raise TelephonyError("Twilio rejected the outbound call request.")

    data = resp.json()
    logger.info("Initiated outbound call sid=%s to=%s", data.get("sid"), mask_phone(to_number))
    return {"call_sid": data.get("sid"), "status": data.get("status")}
