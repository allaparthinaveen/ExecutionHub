from fastapi import APIRouter
from typing import List, Dict, Any
import sys
from pathlib import Path

# Add project root to path so we can import multibagger_engine
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from multibagger_engine.live_scanner import run_live_scanner

router = APIRouter()

@router.get("/scan", response_model=Dict[str, Any])
def scan_multibagger_universe():
    """
    Runs the Multibagger Engine Phase 7 live scanner on the MVRD universe.
    Returns today's live setups that match the quantitative footprint.
    """
    try:
        setups = run_live_scanner()
        return {
            "status": "success",
            "message": f"Scanned {len(setups)} live setups.",
            "data": setups
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "data": []
        }
