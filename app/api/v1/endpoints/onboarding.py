"""
Onboarding API Endpoints

Provides endpoints for:
- Starting a new onboarding session
- Handling onboarding conversation
- Resuming existing sessions
- Checking onboarding status
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.agents.onboarding import (
    OnboardingAgent,
    OnboardingSession,
    OnboardingStep,
    get_onboarding_agent,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# =============================================================================
# Request/Response Models
# =============================================================================

class StartOnboardingResponse(BaseModel):
    """Response when starting a new onboarding session."""
    session_id: str
    message: str
    step: str
    progress_percent: int
    show_input: bool
    input_type: str
    input_options: Optional[List[Dict[str, str]]] = None
    input_placeholder: Optional[str] = None
    action_buttons: Optional[List[Dict[str, str]]] = None


class OnboardingInputRequest(BaseModel):
    """Request to provide input to onboarding."""
    session_id: str
    input_value: str
    input_type: str = "text"


class OnboardingResponse(BaseModel):
    """Response from onboarding input."""
    message: str
    step: str
    progress_percent: int
    show_input: bool
    input_type: str
    input_options: Optional[List[Dict[str, str]]] = None
    input_placeholder: Optional[str] = None
    action_buttons: Optional[List[Dict[str, str]]] = None
    is_complete: bool = False
    next_step: Optional[str] = None


class OnboardingStatusResponse(BaseModel):
    """Current onboarding status."""
    session_id: str
    operator_id: Optional[str]
    current_step: str
    progress_percent: int
    completed_steps: List[str]
    company_name: Optional[str]
    market_name: Optional[str]
    properties_found: int
    is_complete: bool


class ResumeOnboardingResponse(BaseModel):
    """Response when resuming an onboarding session."""
    session_id: str
    message: str
    step: str
    progress_percent: int
    show_input: bool
    input_type: str
    input_options: Optional[List[Dict[str, str]]] = None
    input_placeholder: Optional[str] = None
    action_buttons: Optional[List[Dict[str, str]]] = None
    # Context from session
    company_name: Optional[str] = None
    market_name: Optional[str] = None
    completed_steps: List[str] = []


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/start", response_model=StartOnboardingResponse)
async def start_onboarding(
    db: AsyncSession = Depends(get_async_session),
):
    """
    Start a new onboarding session.
    
    Returns the first message and input prompt.
    """
    agent = await get_onboarding_agent(db)
    session, response = await agent.start_session()
    
    return StartOnboardingResponse(
        session_id=session.session_id,
        message=response.message,
        step=response.step.value,
        progress_percent=response.progress_percent,
        show_input=response.show_input,
        input_type=response.input_type,
        input_options=response.input_options,
        input_placeholder=response.input_placeholder,
        action_buttons=response.action_buttons,
    )


@router.post("/input", response_model=OnboardingResponse)
async def handle_onboarding_input(
    request: OnboardingInputRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Handle user input during onboarding.
    
    This is the main conversational endpoint - send user responses here.
    """
    agent = await get_onboarding_agent(db)
    
    # Get session
    session = await agent.resume_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Onboarding session not found")
    
    # Handle input
    response = await agent.handle_input(
        session=session,
        user_input=request.input_value,
        input_type=request.input_type,
    )
    
    return OnboardingResponse(
        message=response.message,
        step=response.step.value,
        progress_percent=response.progress_percent,
        show_input=response.show_input,
        input_type=response.input_type,
        input_options=response.input_options,
        input_placeholder=response.input_placeholder,
        action_buttons=response.action_buttons,
        is_complete=response.is_complete,
        next_step=response.next_step.value if response.next_step else None,
    )


@router.get("/session/{session_id}", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    session_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Get the current status of an onboarding session."""
    agent = await get_onboarding_agent(db)
    session = await agent.resume_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Onboarding session not found")
    
    progress = int(len(session.completed_steps) / len(OnboardingStep) * 100)
    
    return OnboardingStatusResponse(
        session_id=session.session_id,
        operator_id=session.operator_id,
        current_step=session.current_step.value,
        progress_percent=progress,
        completed_steps=[s.value for s in session.completed_steps],
        company_name=session.company_name,
        market_name=session.market_name,
        properties_found=session.properties_found,
        is_complete=session.current_step == OnboardingStep.COMPLETED,
    )


@router.get("/session/{session_id}/resume", response_model=ResumeOnboardingResponse)
async def resume_onboarding(
    session_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Resume an existing onboarding session.
    
    Returns the current state and next prompt.
    """
    agent = await get_onboarding_agent(db)
    session = await agent.resume_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Onboarding session not found")
    
    # Generate appropriate resume message
    if session.current_step == OnboardingStep.COMPLETED:
        message = (
            f"✅ Your onboarding is complete!\n\n"
            f"**{session.concierge_emoji} {session.concierge_name}** is ready for {session.company_name}."
        )
        show_input = False
        input_type = "text"
        input_options = None
        action_buttons = [
            {"id": "view_dashboard", "label": "View Dashboard"},
        ]
    else:
        # Generate context-aware resume message
        message = (
            f"Welcome back! Let's continue setting up **{session.company_name or 'your concierge'}**.\n\n"
            f"You're on step: **{session.current_step.value.replace('_', ' ').title()}**"
        )
        
        # Get appropriate input prompt for current step
        show_input = True
        input_type = session.pending_question_type or "text"
        input_options = None
        action_buttons = None
    
    progress = int(len(session.completed_steps) / len(OnboardingStep) * 100)
    
    return ResumeOnboardingResponse(
        session_id=session.session_id,
        message=message,
        step=session.current_step.value,
        progress_percent=progress,
        show_input=show_input,
        input_type=input_type,
        input_options=input_options,
        action_buttons=action_buttons,
        company_name=session.company_name,
        market_name=session.market_name,
        completed_steps=[s.value for s in session.completed_steps],
    )


@router.get("/markets")
async def list_supported_markets():
    """List supported markets for onboarding."""
    from app.services.agents.onboarding.onboarding_agent import OnboardingAgent
    
    return {
        "markets": [
            {"id": v["id"], "name": v["name"], "type": v.get("type", "beach")}
            for k, v in OnboardingAgent.SUPPORTED_MARKETS.items()
        ]
    }


@router.get("/pms-providers")
async def list_supported_pms():
    """List supported PMS providers for integration."""
    from app.services.agents.onboarding.onboarding_agent import OnboardingAgent
    
    return {
        "providers": [
            {"id": k, "name": v["name"], "api_docs": v.get("api_docs")}
            for k, v in OnboardingAgent.SUPPORTED_PMS.items()
        ]
    }
