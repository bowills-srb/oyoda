"""
AI Agent Framework - Specialized agents with orchestration.

Provides a framework for AI agents that handle specific tasks:
- Pricing Agent: Rate calculations and discount recommendations
- Market Intel Agent: Market analysis and comp finding
- Lead Qualifier Agent: Score and prioritize prospects
- Voice Assistant Agent: Handle guest and owner inquiries
- Report Writer Agent: Generate pro formas and analyses
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type
from uuid import UUID, uuid4
import asyncio
import json
import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Types of available agents."""
    PRICING = "pricing"
    MARKET_INTEL = "market_intel"
    LEAD_QUALIFIER = "lead_qualifier"
    VOICE_ASSISTANT = "voice_assistant"
    REPORT_WRITER = "report_writer"
    OPERATIONS = "operations"
    ORCHESTRATOR = "orchestrator"
    HEALER = "healer"


class TaskStatus(str, Enum):
    """Status of an agent task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"  # Waiting for human input or external data
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    """Priority levels for tasks."""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5


@dataclass
class AgentContext:
    """
    Context passed to agents for task execution.
    
    Contains all information needed to complete a task.
    """
    # Identity
    company_id: UUID
    user_id: Optional[UUID] = None
    
    # Property context (if applicable)
    property_id: Optional[UUID] = None
    property_data: Optional[Dict[str, Any]] = None
    
    # Property knowledge base (from guest messaging)
    property_knowledge_base: Optional[Dict[str, Any]] = None
    property_faqs: Optional[List[Dict[str, Any]]] = None
    
    # Market context
    market_id: Optional[UUID] = None
    market_data: Optional[Dict[str, Any]] = None
    
    # Conversation context (for voice/chat)
    conversation_id: Optional[UUID] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Request context
    request_id: UUID = field(default_factory=uuid4)
    request_timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Additional data
    additional_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTask:
    """
    A task to be executed by an agent.
    """
    id: UUID = field(default_factory=uuid4)
    task_type: str = ""
    description: str = ""
    
    # Input/Output
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Optional[Dict[str, Any]] = None
    
    # Context
    context: Optional[AgentContext] = None
    
    # Status
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    
    # Routing
    assigned_agent: Optional[AgentType] = None
    requires_agents: List[AgentType] = field(default_factory=list)
    
    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    timeout_seconds: int = 300
    
    # Error handling
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    # Audit
    decision_rationale: Optional[str] = None
    confidence_score: float = 0.0


@dataclass
class AgentResponse:
    """Response from an agent."""
    task_id: UUID
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    confidence: float = 1.0
    rationale: str = ""
    requires_human_review: bool = False
    follow_up_tasks: List[AgentTask] = field(default_factory=list)


class AgentCapability(BaseModel):
    """Definition of an agent capability."""
    name: str
    description: str
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class BaseAgent(ABC):
    """
    Abstract base class for all agents.
    
    Each agent has:
    - A specific role and capabilities
    - Access to relevant tools
    - Constraints and guidelines
    """
    
    agent_type: AgentType = AgentType.ORCHESTRATOR
    name: str = "Base Agent"
    description: str = "Base agent class"
    capabilities: List[AgentCapability] = []
    
    def __init__(
        self,
        llm_client=None,
        tools: List[Any] = None,
        constraints: Dict[str, Any] = None
    ):
        self.llm = llm_client
        self.tools = tools or []
        self.constraints = constraints or {}
        self._task_history: List[AgentTask] = []
    
    @abstractmethod
    async def execute(self, task: AgentTask) -> AgentResponse:
        """Execute a task. Must be implemented by subclasses."""
        pass
    
    async def can_handle(self, task: AgentTask) -> bool:
        """Check if this agent can handle a given task."""
        return task.task_type in [cap.name for cap in self.capabilities]
    
    def add_tool(self, tool: Any):
        """Add a tool to this agent."""
        self.tools.append(tool)
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        return f"""You are {self.name}, an AI agent specialized in {self.description}.

Your capabilities include:
{chr(10).join(f'- {cap.name}: {cap.description}' for cap in self.capabilities)}

Constraints:
{chr(10).join(f'- {k}: {v}' for k, v in self.constraints.items())}

Always provide clear rationale for your decisions and indicate your confidence level.
"""


class PricingAgent(BaseAgent):
    """
    Agent specialized in pricing decisions.
    
    Capabilities:
    - Calculate optimal nightly rates
    - Determine context-aware discounts
    - Forecast revenue impact
    - Detect pricing opportunities
    """
    
    agent_type = AgentType.PRICING
    name = "Pricing Agent"
    description = "dynamic pricing optimization and revenue management"
    
    capabilities = [
        AgentCapability(
            name="calculate_rate",
            description="Calculate optimal nightly rate for a property/date",
            input_schema={
                "property_id": "UUID",
                "target_date": "date",
                "length_of_stay": "int"
            },
            output_schema={
                "recommended_rate": "float",
                "rate_range": {"min": "float", "max": "float"},
                "confidence": "float"
            }
        ),
        AgentCapability(
            name="recommend_discount",
            description="Recommend discount based on market conditions",
            input_schema={
                "property_id": "UUID",
                "target_date": "date",
                "current_rate": "float"
            },
            output_schema={
                "recommended_discount": "float",
                "discount_type": "string",
                "rationale": "string"
            }
        ),
        AgentCapability(
            name="forecast_revenue",
            description="Forecast revenue for a period",
            input_schema={
                "property_id": "UUID",
                "period_start": "date",
                "period_end": "date"
            },
            output_schema={
                "projected_revenue": "float",
                "projected_occupancy": "float",
                "confidence": "float"
            }
        ),
    ]
    
    def __init__(self, discount_engine=None, **kwargs):
        super().__init__(**kwargs)
        self.discount_engine = discount_engine
        self.constraints = {
            "never_below_owner_minimum": True,
            "never_discount_protected_periods_early": True,
            "max_discount_without_approval": 0.20,
        }
    
    async def execute(self, task: AgentTask) -> AgentResponse:
        """Execute a pricing task."""
        try:
            if task.task_type == "calculate_rate":
                return await self._calculate_rate(task)
            elif task.task_type == "recommend_discount":
                return await self._recommend_discount(task)
            elif task.task_type == "forecast_revenue":
                return await self._forecast_revenue(task)
            else:
                return AgentResponse(
                    task_id=task.id,
                    success=False,
                    message=f"Unknown task type: {task.task_type}"
                )
        except Exception as e:
            logger.error(f"Pricing agent error: {e}")
            return AgentResponse(
                task_id=task.id,
                success=False,
                message=str(e)
            )
    
    async def _calculate_rate(self, task: AgentTask) -> AgentResponse:
        """Calculate optimal rate."""
        # Would integrate with rate tables, market data, etc.
        property_data = task.context.property_data or {}
        market_data = task.context.market_data or {}
        
        # Placeholder logic
        base_rate = property_data.get("base_rate", 200)
        season_multiplier = market_data.get("season_multiplier", 1.0)
        
        recommended_rate = base_rate * season_multiplier
        
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "recommended_rate": recommended_rate,
                "rate_range": {
                    "min": recommended_rate * 0.9,
                    "max": recommended_rate * 1.1
                },
                "components": {
                    "base_rate": base_rate,
                    "season_multiplier": season_multiplier,
                }
            },
            confidence=0.85,
            rationale="Rate calculated based on base rate and seasonal adjustment."
        )
    
    async def _recommend_discount(self, task: AgentTask) -> AgentResponse:
        """Recommend discount using the discount engine."""
        # Would call the dynamic discount engine
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "recommended_discount": 0.10,
                "discount_type": "low_demand",
            },
            confidence=0.80,
            rationale="10% discount recommended due to below-average booking pace."
        )
    
    async def _forecast_revenue(self, task: AgentTask) -> AgentResponse:
        """Forecast revenue for a period."""
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "projected_revenue": 15000,
                "projected_occupancy": 0.65,
                "projected_adr": 450,
            },
            confidence=0.75,
            rationale="Forecast based on historical patterns and current booking pace."
        )


class MarketIntelAgent(BaseAgent):
    """
    Agent specialized in market intelligence.
    
    Capabilities:
    - Find comparable properties
    - Analyze market trends
    - Generate competitive analysis
    - Identify opportunities
    """
    
    agent_type = AgentType.MARKET_INTEL
    name = "Market Intelligence Agent"
    description = "market analysis, competitive intelligence, and trend identification"
    
    capabilities = [
        AgentCapability(
            name="find_comps",
            description="Find comparable properties for analysis",
            input_schema={
                "property_id": "UUID",
                "max_results": "int",
                "radius_miles": "float"
            },
            output_schema={
                "comparables": "List[Property]",
                "similarity_scores": "List[float]"
            }
        ),
        AgentCapability(
            name="analyze_trend",
            description="Analyze market trends",
            input_schema={
                "market_id": "UUID",
                "metric": "string",
                "period": "string"
            },
            output_schema={
                "trend_direction": "string",
                "trend_magnitude": "float",
                "forecast": "Dict"
            }
        ),
        AgentCapability(
            name="competitive_analysis",
            description="Generate competitive analysis report",
            input_schema={
                "property_id": "UUID",
                "competitor_ids": "List[UUID]"
            },
            output_schema={
                "analysis": "Dict",
                "recommendations": "List[string]"
            }
        ),
    ]
    
    async def execute(self, task: AgentTask) -> AgentResponse:
        """Execute a market intel task."""
        if task.task_type == "find_comps":
            return await self._find_comps(task)
        elif task.task_type == "analyze_trend":
            return await self._analyze_trend(task)
        else:
            return AgentResponse(
                task_id=task.id,
                success=False,
                message=f"Unknown task type: {task.task_type}"
            )
    
    async def _find_comps(self, task: AgentTask) -> AgentResponse:
        """Find comparable properties."""
        # Would query property database with similarity scoring
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "comparables": [],
                "similarity_scores": [],
            },
            confidence=0.80,
            rationale="Comps found based on location, bedrooms, and amenities."
        )
    
    async def _analyze_trend(self, task: AgentTask) -> AgentResponse:
        """Analyze market trend."""
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "trend_direction": "increasing",
                "trend_magnitude": 0.05,
                "period_analyzed": "90_days",
            },
            confidence=0.75,
            rationale="ADR trending up 5% over past 90 days."
        )


class LeadQualifierAgent(BaseAgent):
    """
    Agent specialized in lead qualification.
    
    Capabilities:
    - Score and rank prospects
    - Qualify leads based on criteria
    - Recommend next actions
    - Route to appropriate team member
    """
    
    agent_type = AgentType.LEAD_QUALIFIER
    name = "Lead Qualifier Agent"
    description = "scoring, qualifying, and routing property prospects"
    
    capabilities = [
        AgentCapability(
            name="score_lead",
            description="Score a property lead",
            input_schema={
                "property_data": "Dict",
                "market_id": "UUID"
            },
            output_schema={
                "score": "float",
                "grade": "string",
                "factors": "Dict"
            }
        ),
        AgentCapability(
            name="qualify_lead",
            description="Determine if lead meets criteria",
            input_schema={
                "property_data": "Dict",
                "criteria": "Dict"
            },
            output_schema={
                "qualified": "bool",
                "reasons": "List[string]"
            }
        ),
        AgentCapability(
            name="route_lead",
            description="Route lead to appropriate team member",
            input_schema={
                "lead_id": "UUID",
                "lead_score": "float"
            },
            output_schema={
                "assigned_to": "UUID",
                "priority": "string"
            }
        ),
    ]
    
    async def execute(self, task: AgentTask) -> AgentResponse:
        """Execute a lead qualification task."""
        if task.task_type == "score_lead":
            return await self._score_lead(task)
        elif task.task_type == "qualify_lead":
            return await self._qualify_lead(task)
        else:
            return AgentResponse(
                task_id=task.id,
                success=False,
                message=f"Unknown task type: {task.task_type}"
            )
    
    async def _score_lead(self, task: AgentTask) -> AgentResponse:
        """Score a property lead."""
        property_data = task.input_data.get("property_data", {})
        
        # Scoring factors
        score = 50.0  # Base score
        factors = {}
        
        # Location (would check against geofence)
        factors["location"] = {"score": 20, "reason": "Within primary market"}
        score += 20
        
        # Property type
        bedrooms = property_data.get("bedrooms", 0)
        if 3 <= bedrooms <= 5:
            factors["bedrooms"] = {"score": 15, "reason": "Ideal bedroom count"}
            score += 15
        
        # Amenities
        if property_data.get("has_pool"):
            factors["pool"] = {"score": 10, "reason": "Has private pool"}
            score += 10
        
        # Determine grade
        if score >= 80:
            grade = "A"
        elif score >= 60:
            grade = "B"
        elif score >= 40:
            grade = "C"
        else:
            grade = "D"
        
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "score": score,
                "grade": grade,
                "factors": factors,
            },
            confidence=0.85,
            rationale=f"Lead scored {score}/100 (Grade {grade}) based on location, size, and amenities."
        )
    
    async def _qualify_lead(self, task: AgentTask) -> AgentResponse:
        """Qualify a lead against criteria."""
        property_data = task.input_data.get("property_data", {})
        criteria = task.input_data.get("criteria", {})
        
        qualified = True
        reasons = []
        
        # Check minimum bedrooms
        min_bedrooms = criteria.get("min_bedrooms", 0)
        if property_data.get("bedrooms", 0) < min_bedrooms:
            qualified = False
            reasons.append(f"Below minimum bedrooms ({min_bedrooms})")
        
        # Check location
        if criteria.get("require_in_geofence") and not property_data.get("in_geofence"):
            qualified = False
            reasons.append("Outside target market area")
        
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "qualified": qualified,
                "reasons": reasons if not qualified else ["Meets all criteria"],
            },
            confidence=0.90,
            rationale="Lead qualified against company criteria."
        )


class VoiceAssistantAgent(BaseAgent):
    """
    Agent specialized in voice/chat interactions.
    
    Capabilities:
    - Answer property questions
    - Provide availability and pricing
    - Handle booking inquiries
    - Route complex requests
    """
    
    agent_type = AgentType.VOICE_ASSISTANT
    name = "Voice Assistant Agent"
    description = "handling guest and owner inquiries via voice or chat"
    
    capabilities = [
        AgentCapability(
            name="answer_question",
            description="Answer a question about a property or booking",
            input_schema={
                "question": "string",
                "property_id": "UUID",
                "conversation_history": "List[Dict]"
            },
            output_schema={
                "answer": "string",
                "confidence": "float",
                "requires_human": "bool"
            }
        ),
        AgentCapability(
            name="check_availability",
            description="Check availability for dates",
            input_schema={
                "property_id": "UUID",
                "check_in": "date",
                "check_out": "date"
            },
            output_schema={
                "available": "bool",
                "rate": "float",
                "alternative_dates": "List[Dict]"
            }
        ),
    ]
    
    async def execute(self, task: AgentTask) -> AgentResponse:
        """Execute a voice assistant task."""
        if task.task_type == "answer_question":
            return await self._answer_question(task)
        elif task.task_type == "check_availability":
            return await self._check_availability(task)
        else:
            return AgentResponse(
                task_id=task.id,
                success=False,
                message=f"Unknown task type: {task.task_type}"
            )
    
    async def _answer_question(self, task: AgentTask) -> AgentResponse:
        """Answer a question using LLM with property context."""
        question = task.input_data.get("question", "")
        property_data = task.context.property_data or {}
        
        # Would call LLM with property context
        # For now, return placeholder
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "answer": f"I'd be happy to help with your question about this property.",
                "requires_human": False,
            },
            confidence=0.85,
            rationale="Answer generated from property knowledge base."
        )
    
    async def _check_availability(self, task: AgentTask) -> AgentResponse:
        """Check availability for dates."""
        # Would query calendar/PMS
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={
                "available": True,
                "rate": 450.00,
                "total": 2250.00,
            },
            confidence=0.95,
            rationale="Availability confirmed from booking calendar."
        )


# =============================================================================
# Agent Orchestrator
# =============================================================================

class AgentOrchestrator:
    """
    Orchestrates multiple agents to complete complex tasks.
    
    Responsibilities:
    - Route tasks to appropriate agents
    - Coordinate multi-agent workflows
    - Manage agent state and context
    - Handle errors and retries
    """
    
    def __init__(self):
        self._agents: Dict[AgentType, BaseAgent] = {}
        self._task_queue: List[AgentTask] = []
        self._completed_tasks: Dict[UUID, AgentTask] = {}
    
    def register_agent(self, agent: BaseAgent):
        """Register an agent with the orchestrator."""
        self._agents[agent.agent_type] = agent
        logger.info(f"Registered agent: {agent.name} ({agent.agent_type})")
    
    def get_agent(self, agent_type: AgentType) -> Optional[BaseAgent]:
        """Get a registered agent by type."""
        return self._agents.get(agent_type)
    
    async def route_task(self, task: AgentTask) -> AgentType:
        """Determine which agent should handle a task."""
        # Check if task specifies an agent
        if task.assigned_agent:
            return task.assigned_agent
        
        # Find capable agent
        for agent_type, agent in self._agents.items():
            if await agent.can_handle(task):
                return agent_type
        
        # Default to orchestrator for complex tasks
        return AgentType.ORCHESTRATOR
    
    async def execute_task(
        self,
        task: AgentTask,
        context: AgentContext = None
    ) -> AgentResponse:
        """
        Execute a task, routing to appropriate agent(s).
        """
        if context:
            task.context = context
        
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.utcnow()
        
        try:
            # Route to appropriate agent
            agent_type = await self.route_task(task)
            agent = self._agents.get(agent_type)
            
            if not agent:
                raise ValueError(f"No agent registered for type: {agent_type}")
            
            task.assigned_agent = agent_type
            logger.info(f"Routing task {task.id} to {agent.name}")
            
            # Execute
            response = await agent.execute(task)
            
            # Update task status
            task.status = TaskStatus.COMPLETED if response.success else TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.output_data = response.data
            task.decision_rationale = response.rationale
            task.confidence_score = response.confidence
            
            if not response.success:
                task.error_message = response.message
            
            # Store completed task
            self._completed_tasks[task.id] = task
            
            # Handle follow-up tasks
            for follow_up in response.follow_up_tasks:
                await self.execute_task(follow_up, context)
            
            return response
            
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            
            return AgentResponse(
                task_id=task.id,
                success=False,
                message=str(e)
            )
    
    async def execute_workflow(
        self,
        tasks: List[AgentTask],
        context: AgentContext,
        parallel: bool = False
    ) -> List[AgentResponse]:
        """
        Execute multiple tasks as a workflow.
        
        Args:
            tasks: List of tasks to execute
            context: Shared context for all tasks
            parallel: Whether to execute tasks in parallel
        """
        if parallel:
            # Execute all tasks concurrently
            responses = await asyncio.gather(*[
                self.execute_task(task, context) for task in tasks
            ])
            return list(responses)
        else:
            # Execute sequentially, passing output to next task
            responses = []
            for task in tasks:
                response = await self.execute_task(task, context)
                responses.append(response)
                
                # Pass output to next task's context
                if response.success and response.data:
                    context.additional_context.update(response.data)
            
            return responses
