from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.valuation import (
    ScreenUniverseRequest,
    ScreenUniverseResponse,
    ValuationRequest,
    ValuationResponse
)
from app.services.valuation import ValuationService
from app.api.dependencies import get_current_user

router = APIRouter()

@router.post("/screen", response_model=ScreenUniverseResponse)
async def screen_universe(
    request: ScreenUniverseRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Phase 1: Multi-stage Life-Cycle Screener Endpoint.
    Accepts a list of tickers and filters/ranks them based on Damodaran's
    structural criteria for the target life-cycle stage.
    """
    valid_stages = ['young_growth', 'mature_value', 'declining_turnaround']
    if request.stage not in valid_stages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage. Must be one of: {', '.join(valid_stages)}"
        )
    
    try:
        candidates = await ValuationService.screen_universe(request.tickers, request.stage)
        return ScreenUniverseResponse(stage=request.stage, candidates=candidates)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Screener run failed: {str(e)}"
        )

@router.post("/getValuation", response_model=ValuationResponse)
async def get_valuation(
    request: ValuationRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Phase 2: Three-Appraisal Intrinsic Value Endpoint.
    Extracts 3-year financials and runs an automated 3-appraisal DCF model.
    """
    overrides = {}
    if request.risk_free_rate_override is not None:
        overrides['risk_free_rate_override'] = request.risk_free_rate_override
    if request.erp_override is not None:
        overrides['erp_override'] = request.erp_override
    if request.cost_of_debt_override is not None:
        overrides['cost_of_debt_override'] = request.cost_of_debt_override
    if request.growth_rate_override is not None:
        overrides['growth_rate_override'] = request.growth_rate_override
    if request.tax_rate_override is not None:
        overrides['tax_rate_override'] = request.tax_rate_override
    if request.stable_growth_rate_override is not None:
        overrides['stable_growth_rate_override'] = request.stable_growth_rate_override

    try:
        response = await ValuationService.calculate_intrinsic_value(request.ticker, overrides)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Valuation modeling failed for {request.ticker}: {str(e)}"
        )
