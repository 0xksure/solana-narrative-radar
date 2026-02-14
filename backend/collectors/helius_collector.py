"""Collect onchain signals from Helius API"""
import logging

logger = logging.getLogger(__name__)

import httpx
import os
from datetime import datetime
from typing import List, Dict

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
BASE_URL = f"https://api.helius.xyz/v0"

async def collect_program_activity() -> List[Dict]:
    """Track program activity and new deployments on Solana"""
    signals = []
    
    if not HELIUS_API_KEY:
        logger.warning("No Helius API key set, skipping onchain collection")
        return signals
    
    # Note: Helius free tier has limited endpoints
    # We can use enhanced transaction history and DAS API
    async with httpx.AsyncClient() as client:
        # Get recent notable transactions/programs via Helius
        # For MVP, we'll focus on what's available in free tier
        pass
    
    return signals
