"""Solana wallet authentication and spam reporting endpoints."""
import json
import os
import time
import base64
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import nacl.signing
import nacl.exceptions

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SPAM_REPORTS_PATH = os.path.join(DATA_DIR, "spam_reports.json")

# Simple secret for token signing (not critical for MVP)
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "narrative-radar-mvp-secret-change-me")


# --- Models ---

class VerifyWalletRequest(BaseModel):
    pubkey: str
    message: str
    signature: str  # base64-encoded


class SpamReportRequest(BaseModel):
    signal_id: str
    wallet: str


# --- Token helpers ---

def _sign_token(pubkey: str) -> str:
    """Create a simple signed token: base64(pubkey:timestamp:hmac)."""
    ts = str(int(time.time()))
    payload = f"{pubkey}:{ts}"
    sig = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    token_data = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(token_data.encode()).decode()


def _verify_token(token: str) -> Optional[str]:
    """Verify token, return pubkey or None. Tokens valid for 7 days."""
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        if len(parts) != 3:
            return None
        pubkey, ts_str, sig = parts
        # Check expiry (7 days)
        if time.time() - int(ts_str) > 7 * 86400:
            return None
        # Verify HMAC
        payload = f"{pubkey}:{ts_str}"
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        return pubkey
    except Exception:
        return None


# --- Spam report storage ---

def _load_spam_reports() -> dict:
    try:
        with open(SPAM_REPORTS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"reports": []}


def _save_spam_reports(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SPAM_REPORTS_PATH, "w") as f:
        json.dump(data, f, indent=2)


# --- Endpoints ---

@router.post("/verify-wallet")
async def verify_wallet(req: VerifyWalletRequest):
    """Verify a Solana wallet signature and return an auth token."""
    try:
        # Decode the public key from base58
        pubkey_bytes = _base58_decode(req.pubkey)
        if len(pubkey_bytes) != 32:
            raise HTTPException(status_code=400, detail="Invalid public key length")

        # Decode the signature from base64
        sig_bytes = base64.b64decode(req.signature)
        if len(sig_bytes) != 64:
            raise HTTPException(status_code=400, detail="Invalid signature length")

        # Verify the Ed25519 signature
        verify_key = nacl.signing.VerifyKey(pubkey_bytes)
        verify_key.verify(req.message.encode(), sig_bytes)

    except nacl.exceptions.BadSignatureError:
        raise HTTPException(status_code=401, detail="Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Verification failed: {str(e)}")

    token = _sign_token(req.pubkey)
    return {"token": token, "pubkey": req.pubkey}


@router.post("/signal/spam")
async def report_spam(req: SpamReportRequest, authorization: Optional[str] = Header(None)):
    """Report a signal as spam. Requires wallet auth."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Auth required")

    token = authorization[7:]
    wallet = _verify_token(token)
    if not wallet:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if wallet != req.wallet:
        raise HTTPException(status_code=403, detail="Token wallet mismatch")

    data = _load_spam_reports()

    # Check if already reported
    for r in data["reports"]:
        if r["signal_id"] == req.signal_id and r["wallet"] == req.wallet:
            return {"status": "already_reported"}

    data["reports"].append({
        "signal_id": req.signal_id,
        "wallet": req.wallet,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_spam_reports(data)

    return {"status": "reported"}


@router.get("/signal/spam-counts")
async def get_spam_counts():
    """Return spam report counts per signal_id."""
    data = _load_spam_reports()
    counts = {}
    for r in data["reports"]:
        sid = r["signal_id"]
        if sid not in counts:
            counts[sid] = {"count": 0, "wallets": []}
        counts[sid]["count"] += 1
        counts[sid]["wallets"].append(r["wallet"])
    # Simplify: just count and unique wallets
    result = {}
    for sid, info in counts.items():
        unique = len(set(info["wallets"]))
        result[sid] = unique
    return result


# --- Base58 decoder (avoid extra dependency) ---

_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_decode(s: str) -> bytes:
    """Decode a base58-encoded string."""
    n = 0
    for c in s.encode():
        n = n * 58 + _B58_ALPHABET.index(c)
    result = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    # Add leading zero bytes for leading '1's
    pad = 0
    for c in s:
        if c == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + result
