"""
Onboarding Agent - Walks operators through setup.

The onboarding agent is a conversational agent that:
1. Captures company basics and branding
2. Sets up PMS integration or configures web scraping
3. Runs through policy questionnaire
4. Enriches property data with missing info
5. Builds the knowledge base
6. Activates the operator's concierge

The agent maintains conversation state so operators can pause
and resume onboarding at any time.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class OnboardingStep(str, Enum):
    """Steps in the onboarding flow."""
    WELCOME = "welcome"
    BASICS = "basics"  # Company name, market
    BRANDING = "branding"  # Logo, colors, persona
    INTEGRATION = "integration"  # PMS or scraper setup
    POLICIES = "policies"  # Policy questionnaire
    PROPERTIES = "properties"  # Property data enrichment
    KNOWLEDGE_BASE = "knowledge_base"  # Index everything
    ACTIVATION = "activation"  # Final activation
    COMPLETED = "completed"


@dataclass
class OnboardingSession:
    """State of an onboarding session."""
    session_id: str = field(default_factory=lambda: f"onb_{uuid4().hex[:12]}")
    operator_id: Optional[str] = None
    
    # Progress
    current_step: OnboardingStep = OnboardingStep.WELCOME
    completed_steps: List[OnboardingStep] = field(default_factory=list)
    
    # Collected data
    company_name: Optional[str] = None
    company_code: Optional[str] = None
    market_id: Optional[str] = None
    market_name: Optional[str] = None
    
    # Branding
    logo_url: Optional[str] = None
    primary_color: str = "#0ea5e9"
    secondary_color: str = "#0284c7"
    concierge_name: str = "Coral"
    concierge_emoji: str = "🐚"
    
    # Integration
    integration_type: Optional[str] = None  # pms, scraper, manual
    pms_provider: Optional[str] = None
    pms_connected: bool = False
    properties_found: int = 0
    
    # Policies (captured as dict)
    policies: Dict[str, Any] = field(default_factory=dict)
    
    # Properties needing enrichment
    properties_to_enrich: List[str] = field(default_factory=list)
    enriched_properties: List[str] = field(default_factory=list)
    
    # Knowledge base
    documents_indexed: int = 0
    
    # Conversation
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    pending_question: Optional[str] = None
    pending_question_type: Optional[str] = None
    
    # Timestamps
    started_at: datetime = field(default_factory=datetime.utcnow)
    last_activity_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "session_id": self.session_id,
            "operator_id": self.operator_id,
            "current_step": self.current_step.value,
            "completed_steps": [s.value for s in self.completed_steps],
            "company_name": self.company_name,
            "company_code": self.company_code,
            "market_id": self.market_id,
            "market_name": self.market_name,
            "logo_url": self.logo_url,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "concierge_name": self.concierge_name,
            "concierge_emoji": self.concierge_emoji,
            "integration_type": self.integration_type,
            "pms_provider": self.pms_provider,
            "pms_connected": self.pms_connected,
            "properties_found": self.properties_found,
            "policies": self.policies,
            "properties_to_enrich": self.properties_to_enrich,
            "enriched_properties": self.enriched_properties,
            "documents_indexed": self.documents_indexed,
            "conversation_history": self.conversation_history,
            "pending_question": self.pending_question,
            "pending_question_type": self.pending_question_type,
            "started_at": self.started_at.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OnboardingSession":
        """Deserialize from storage."""
        session = cls(
            session_id=data.get("session_id", f"onb_{uuid4().hex[:12]}"),
            operator_id=data.get("operator_id"),
            current_step=OnboardingStep(data.get("current_step", "welcome")),
            completed_steps=[OnboardingStep(s) for s in data.get("completed_steps", [])],
            company_name=data.get("company_name"),
            company_code=data.get("company_code"),
            market_id=data.get("market_id"),
            market_name=data.get("market_name"),
            logo_url=data.get("logo_url"),
            primary_color=data.get("primary_color", "#0ea5e9"),
            secondary_color=data.get("secondary_color", "#0284c7"),
            concierge_name=data.get("concierge_name", "Coral"),
            concierge_emoji=data.get("concierge_emoji", "🐚"),
            integration_type=data.get("integration_type"),
            pms_provider=data.get("pms_provider"),
            pms_connected=data.get("pms_connected", False),
            properties_found=data.get("properties_found", 0),
            policies=data.get("policies", {}),
            properties_to_enrich=data.get("properties_to_enrich", []),
            enriched_properties=data.get("enriched_properties", []),
            documents_indexed=data.get("documents_indexed", 0),
            conversation_history=data.get("conversation_history", []),
            pending_question=data.get("pending_question"),
            pending_question_type=data.get("pending_question_type"),
        )
        
        if data.get("started_at"):
            session.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("last_activity_at"):
            session.last_activity_at = datetime.fromisoformat(data["last_activity_at"])
        if data.get("completed_at"):
            session.completed_at = datetime.fromisoformat(data["completed_at"])
        
        return session


@dataclass
class OnboardingResponse:
    """Response from the onboarding agent."""
    message: str
    step: OnboardingStep
    progress_percent: int
    
    # UI hints
    show_input: bool = True
    input_type: str = "text"  # text, select, multiselect, file, secure
    input_options: Optional[List[Dict[str, str]]] = None  # For select
    input_placeholder: Optional[str] = None
    
    # Actions
    action_buttons: Optional[List[Dict[str, str]]] = None
    # [{"id": "skip", "label": "Skip for now"}, {"id": "help", "label": "I need help"}]
    
    # State
    is_complete: bool = False
    next_step: Optional[OnboardingStep] = None


class OnboardingAgent:
    """
    Conversational agent for operator onboarding.
    
    Usage:
        agent = OnboardingAgent(db_session)
        
        # Start new session
        session, response = await agent.start_session()
        
        # Handle user input
        response = await agent.handle_input(session, "Beach Habitats")
        
        # Resume existing session
        session = await agent.resume_session("onb_abc123")
    """
    
    # Markets we support
    SUPPORTED_MARKETS = {
        # ── Florida beach / curated ──────────────────────────────────────
        "30a": {"id": "MARKET_30A", "name": "30A Florida", "type": "beach"},
        "destin": {"id": "MARKET_DESTIN", "name": "Destin Florida", "type": "beach"},
        "pcb": {"id": "MARKET_PCB", "name": "Panama City Beach", "type": "beach"},
        "gulf_shores": {"id": "MARKET_GULF_SHORES", "name": "Gulf Shores Alabama", "type": "beach"},
        # ── Florida large city markets (Places API) ──────────────────────
        "miami": {"id": "MARKET_MIAMI", "name": "Miami, Florida", "type": "city"},
        "miami_beach": {"id": "MARKET_MIAMI", "name": "Miami Beach, Florida", "type": "city"},
        "brickell": {"id": "MARKET_MIAMI", "name": "Brickell / Miami", "type": "city"},
        "orlando": {"id": "MARKET_ORLANDO", "name": "Orlando, Florida", "type": "theme_park"},
        "kissimmee": {"id": "MARKET_ORLANDO", "name": "Kissimmee / Orlando", "type": "theme_park"},
        "tampa": {"id": "MARKET_TAMPA", "name": "Tampa Bay, Florida", "type": "city"},
        "clearwater": {"id": "MARKET_TAMPA", "name": "Clearwater Beach", "type": "beach"},
        "st_pete": {"id": "MARKET_TAMPA", "name": "St. Petersburg, Florida", "type": "city"},
        "keys": {"id": "MARKET_KEYS", "name": "Florida Keys", "type": "beach"},
        "key_west": {"id": "MARKET_KEYS", "name": "Key West, Florida", "type": "beach"},
        "naples": {"id": "MARKET_NAPLES", "name": "Naples / Fort Myers", "type": "beach"},
        "marco_island": {"id": "MARKET_NAPLES", "name": "Marco Island, Florida", "type": "beach"},
        # ── Mountain / other ─────────────────────────────────────────────
        "park_city": {"id": "MARKET_PARK_CITY", "name": "Park City Utah", "type": "mountain"},
        "steamboat": {"id": "MARKET_STEAMBOAT", "name": "Steamboat Colorado", "type": "mountain"},
        "gatlinburg": {"id": "MARKET_GATLINBURG", "name": "Gatlinburg Tennessee", "type": "mountain"},
    }
    
    # Supported PMS providers
    SUPPORTED_PMS = {
        "escapia": {"name": "Escapia (Vrbo)", "api_docs": "https://developer.vrbo.com"},
        "guesty": {"name": "Guesty", "api_docs": "https://api.guesty.com"},
        "hostaway": {"name": "Hostaway", "api_docs": "https://api.hostaway.com"},
        "track": {"name": "Track", "api_docs": "https://www.trackhs.com/api"},
        "streamline": {"name": "Streamline", "api_docs": "https://www.streamlinevrs.com"},
        "lodgify": {"name": "Lodgify", "api_docs": "https://www.lodgify.com/docs"},
        "hostfully": {"name": "Hostfully", "api_docs": "https://www.hostfully.com/api"},
    }
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._sessions: Dict[str, OnboardingSession] = {}
    
    async def start_session(self) -> tuple[OnboardingSession, OnboardingResponse]:
        """Start a new onboarding session."""
        session = OnboardingSession()
        self._sessions[session.session_id] = session
        
        response = OnboardingResponse(
            message=self._get_welcome_message(),
            step=OnboardingStep.WELCOME,
            progress_percent=0,
            show_input=True,
            input_type="text",
            input_placeholder="Enter your company name",
            action_buttons=[
                {"id": "help", "label": "I have questions first"},
            ],
        )
        
        session.pending_question = "company_name"
        session.pending_question_type = "text"
        session.current_step = OnboardingStep.BASICS
        
        return session, response
    
    async def resume_session(self, session_id: str) -> Optional[OnboardingSession]:
        """Resume an existing session — checks memory then DB."""
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Load from DB
        try:
            from sqlalchemy import text
            result = await self.db.execute(
                text("SELECT session_data FROM concierge_onboarding_sessions WHERE session_id = :sid LIMIT 1"),
                {"sid": session_id},
            )
            row = result.fetchone()
            if row:
                import json as _json
                session = OnboardingSession.from_dict(_json.loads(row[0]))
                self._sessions[session_id] = session
                return session
        except Exception as e:
            logger.warning(f"Onboarding session DB load failed: {e}")

        return None

    async def save_session(self, session: OnboardingSession) -> None:
        """Persist onboarding session to DB."""
        self._sessions[session.session_id] = session
        try:
            import json as _json
            from sqlalchemy import text
            await self.db.execute(
                text("""
                    INSERT INTO concierge_onboarding_sessions (session_id, session_data, updated_at)
                    VALUES (:sid, :data, now())
                    ON CONFLICT (session_id) DO UPDATE SET
                        session_data = EXCLUDED.session_data,
                        updated_at = now()
                """),
                {"sid": session.session_id, "data": _json.dumps(session.to_dict())},
            )
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Onboarding session DB save failed: {e}")
    
    async def handle_input(
        self,
        session: OnboardingSession,
        user_input: str,
        input_type: str = "text",
    ) -> OnboardingResponse:
        """
        Handle user input and advance the onboarding flow.
        
        This is the main conversational loop.
        """
        session.last_activity_at = datetime.utcnow()
        session.conversation_history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # Save session state to DB after every input
        await self.save_session(session)

        # Route based on current step and pending question
        if session.current_step == OnboardingStep.BASICS:
            return await self._handle_basics(session, user_input)
        
        elif session.current_step == OnboardingStep.BRANDING:
            return await self._handle_branding(session, user_input)
        
        elif session.current_step == OnboardingStep.INTEGRATION:
            return await self._handle_integration(session, user_input)
        
        elif session.current_step == OnboardingStep.POLICIES:
            return await self._handle_policies(session, user_input)
        
        elif session.current_step == OnboardingStep.PROPERTIES:
            return await self._handle_properties(session, user_input)
        
        elif session.current_step == OnboardingStep.KNOWLEDGE_BASE:
            return await self._handle_knowledge_base(session, user_input)
        
        elif session.current_step == OnboardingStep.ACTIVATION:
            return await self._handle_activation(session, user_input)
        
        else:
            return self._create_response(
                session,
                "I'm not sure where we are. Let me start over.",
                show_input=True,
            )
    
    # =========================================================================
    # Step Handlers
    # =========================================================================
    
    async def _handle_basics(
        self,
        session: OnboardingSession,
        user_input: str,
    ) -> OnboardingResponse:
        """Handle BASICS step - company name and market."""
        
        if session.pending_question == "company_name":
            # Save company name
            session.company_name = user_input.strip()
            session.company_code = self._generate_code(session.company_name)
            session.operator_id = f"op_{session.company_code.lower()}"
            
            # Ask for market
            session.pending_question = "market"
            session.pending_question_type = "select"
            
            market_options = [
                {"value": k, "label": v["name"]}
                for k, v in self.SUPPORTED_MARKETS.items()
            ]
            
            return OnboardingResponse(
                message=f"Great! **{session.company_name}** - love it! 🎉\n\n"
                       f"What market/region do you operate in?",
                step=OnboardingStep.BASICS,
                progress_percent=10,
                show_input=True,
                input_type="select",
                input_options=market_options,
                action_buttons=[
                    {"id": "other_market", "label": "My market isn't listed"},
                ],
            )
        
        elif session.pending_question == "market":
            # Save market
            market_key = user_input.lower().strip()
            if market_key in self.SUPPORTED_MARKETS:
                market = self.SUPPORTED_MARKETS[market_key]
                session.market_id = market["id"]
                session.market_name = market["name"]
            else:
                # Custom market
                session.market_id = f"MARKET_{user_input.upper().replace(' ', '_')}"
                session.market_name = user_input
            
            # Move to branding
            session.completed_steps.append(OnboardingStep.BASICS)
            session.current_step = OnboardingStep.BRANDING
            session.pending_question = "logo"
            session.pending_question_type = "file"
            
            return OnboardingResponse(
                message=f"📍 **{session.market_name}** - great market!\n\n"
                       f"Now let's customize your concierge. First, can you share your logo?\n\n"
                       f"You can paste a URL or upload an image.",
                step=OnboardingStep.BRANDING,
                progress_percent=20,
                show_input=True,
                input_type="text",
                input_placeholder="https://yoursite.com/logo.png",
                action_buttons=[
                    {"id": "skip_logo", "label": "Skip for now"},
                    {"id": "upload", "label": "Upload image"},
                ],
            )
        
        return self._unknown_input_response(session)
    
    async def _handle_branding(
        self,
        session: OnboardingSession,
        user_input: str,
    ) -> OnboardingResponse:
        """Handle BRANDING step - logo, colors, persona."""
        
        if session.pending_question == "logo":
            if user_input.lower() not in ["skip", "skip for now"]:
                session.logo_url = user_input.strip()
            
            session.pending_question = "colors"
            
            return OnboardingResponse(
                message="What are your brand colors? I'll use these for the guest interface.\n\n"
                       "Format: primary color, secondary color (e.g., `#C9A227, #2D8C8C`)\n\n"
                       "Or I can use nice defaults!",
                step=OnboardingStep.BRANDING,
                progress_percent=25,
                show_input=True,
                input_type="text",
                input_placeholder="#C9A227, #2D8C8C",
                action_buttons=[
                    {"id": "use_defaults", "label": "Use defaults"},
                    {"id": "extract_from_logo", "label": "Extract from logo"},
                ],
            )
        
        elif session.pending_question == "colors":
            if user_input.lower() not in ["use defaults", "defaults"]:
                colors = user_input.replace(" ", "").split(",")
                if len(colors) >= 1:
                    session.primary_color = colors[0]
                if len(colors) >= 2:
                    session.secondary_color = colors[1]
            
            session.pending_question = "concierge_name"
            
            # Suggest names based on market type
            market_type = "beach"
            for mk, mv in self.SUPPORTED_MARKETS.items():
                if mv["id"] == session.market_id:
                    market_type = mv.get("type", "beach")
                    break
            
            name_suggestions = {
                "beach": ["Coral", "Sandy", "Marina", "Shelly", "Finn"],
                "mountain": ["Aspen", "Summit", "Ridge", "Everest", "Alpine"],
                "city": ["Metro", "Urban", "City", "Scout", "Guide"],
                "lake": ["Marina", "Harbor", "Lakely", "Anchor", "Wave"],
            }
            
            suggestions = name_suggestions.get(market_type, name_suggestions["beach"])
            
            return OnboardingResponse(
                message="What should we name your concierge? This is who guests will interact with.\n\n"
                       f"Some ideas for {market_type} markets: **{', '.join(suggestions)}**",
                step=OnboardingStep.BRANDING,
                progress_percent=30,
                show_input=True,
                input_type="text",
                input_placeholder="Coral",
            )
        
        elif session.pending_question == "concierge_name":
            session.concierge_name = user_input.strip()
            session.pending_question = "concierge_emoji"
            
            return OnboardingResponse(
                message=f"**{session.concierge_name}** - perfect! 🎉\n\n"
                       f"What emoji represents {session.concierge_name}?",
                step=OnboardingStep.BRANDING,
                progress_percent=35,
                show_input=True,
                input_type="text",
                input_placeholder="🐚",
            )
        
        elif session.pending_question == "concierge_emoji":
            session.concierge_emoji = user_input.strip()
            
            # Move to integration
            session.completed_steps.append(OnboardingStep.BRANDING)
            session.current_step = OnboardingStep.INTEGRATION
            session.pending_question = "integration_type"
            
            pms_options = [
                {"value": k, "label": v["name"]}
                for k, v in self.SUPPORTED_PMS.items()
            ]
            
            return OnboardingResponse(
                message=f"{session.concierge_emoji} {session.concierge_name} is ready to help!\n\n"
                       f"Now let's connect your property data. How would you like to import properties?\n\n"
                       f"**1️⃣ PMS Integration** (recommended)\n"
                       f"Auto-syncs properties, bookings, and pricing\n\n"
                       f"**2️⃣ Local Files**\n"
                       f"Scan your spreadsheets, documents, and PDFs\n\n"
                       f"**3️⃣ Website Import**\n"
                       f"I'll analyze your website and import properties\n\n"
                       f"**4️⃣ Manual Entry**\n"
                       f"Add properties one by one",
                step=OnboardingStep.INTEGRATION,
                progress_percent=40,
                show_input=True,
                input_type="select",
                input_options=[
                    {"value": "pms", "label": "PMS Integration"},
                    {"value": "local_files", "label": "Local Files (Excel, Word, PDF)"},
                    {"value": "scraper", "label": "Website Import"},
                    {"value": "manual", "label": "Manual Entry"},
                ],
            )
        
        return self._unknown_input_response(session)
    
    async def _handle_integration(
        self,
        session: OnboardingSession,
        user_input: str,
    ) -> OnboardingResponse:
        """Handle INTEGRATION step - PMS or scraper setup."""
        
        if session.pending_question == "integration_type":
            session.integration_type = user_input.lower().strip()
            
            if session.integration_type == "pms":
                session.pending_question = "pms_provider"
                
                pms_options = [
                    {"value": k, "label": v["name"]}
                    for k, v in self.SUPPORTED_PMS.items()
                ]
                
                return OnboardingResponse(
                    message="Which PMS do you use?",
                    step=OnboardingStep.INTEGRATION,
                    progress_percent=45,
                    show_input=True,
                    input_type="select",
                    input_options=pms_options,
                    action_buttons=[
                        {"id": "other_pms", "label": "My PMS isn't listed"},
                    ],
                )
            
            elif session.integration_type == "scraper":
                session.pending_question = "website_url"
                
                return OnboardingResponse(
                    message="What's your website URL? I'll analyze it and import your properties.\n\n"
                           "Note: This requires your authorization to scrape.",
                    step=OnboardingStep.INTEGRATION,
                    progress_percent=45,
                    show_input=True,
                    input_type="text",
                    input_placeholder="https://yourcompany.com",
                )
            
            elif session.integration_type == "local_files":
                session.pending_question = "files_directory"
                
                return OnboardingResponse(
                    message="📁 **Local Files Import**\n\n"
                           "I can scan your local files for property data:\n"
                           "• Excel spreadsheets (property lists, rates)\n"
                           "• Word documents (house manuals, guides)\n"
                           "• PDFs (contracts, welcome packets)\n\n"
                           "What folder should I scan? (e.g., ~/Documents/Properties)",
                    step=OnboardingStep.INTEGRATION,
                    progress_percent=45,
                    show_input=True,
                    input_type="text",
                    input_placeholder="~/Documents/Properties",
                    action_buttons=[
                        {"id": "browse", "label": "Browse folders"},
                    ],
                )
            
            else:  # manual
                # Skip to policies
                session.completed_steps.append(OnboardingStep.INTEGRATION)
                session.current_step = OnboardingStep.POLICIES
                return await self._start_policies(session)
        
        elif session.pending_question == "pms_provider":
            session.pms_provider = user_input.lower().strip()
            session.pending_question = "pms_credentials"
            
            pms_name = self.SUPPORTED_PMS.get(session.pms_provider, {}).get("name", session.pms_provider)
            
            return OnboardingResponse(
                message=f"To connect {pms_name}, I'll need your API credentials.\n\n"
                       f"These are stored securely and only used to sync your data.\n\n"
                       f"Please enter your API Key:",
                step=OnboardingStep.INTEGRATION,
                progress_percent=50,
                show_input=True,
                input_type="secure",
                input_placeholder="Your API Key",
                action_buttons=[
                    {"id": "help_credentials", "label": "Where do I find this?"},
                ],
            )
        
        elif session.pending_question == "pms_credentials":
            # Store API key in session for later use by PMSIngestWorker
            # (credentials are held in-session only; worker persists them
            #  encrypted via IntegrationCredentialStore on activation)
            session.policies["_pms_api_key"] = user_input.strip()

            # Attempt live connection + listing fetch
            pms_name = self.SUPPORTED_PMS.get(session.pms_provider or "", {}).get("name", session.pms_provider)
            properties_found = 0
            connect_error: str | None = None

            try:
                from app.services.connectors.pms_connectors import PMSConnectorFactory, PMSProvider
                provider_enum = PMSProvider(session.pms_provider)
                connector = PMSConnectorFactory.create_connector(
                    provider=provider_enum,
                    tenant_id=session.operator_id or session.session_id,
                    credentials_key="_inline_",  # raw creds path
                )
                # Inject raw credentials directly (bypass vault for onboarding)
                connector.credentials = {
                    "api_key": user_input.strip(),
                    "account_id": session.policies.get("_pms_account_id", ""),
                }
                ok, msg = await connector.test_connection()
                if ok:
                    listings = await connector.fetch_listings()
                    session.policies["_pms_listings"] = [
                        l.dict() if hasattr(l, "dict") else vars(l) for l in listings
                    ]
                    properties_found = len(listings)
                    session.pms_connected = True
                else:
                    connect_error = msg
            except Exception as exc:
                logger.warning("[Onboarding] PMS connect failed (non-fatal): %s", exc)
                connect_error = str(exc)

            session.properties_found = properties_found
            session.completed_steps.append(OnboardingStep.INTEGRATION)
            session.current_step = OnboardingStep.POLICIES

            if connect_error:
                note = (
                    f"⚠️ Couldn't connect automatically ({connect_error[:120]}).\n"
                    f"You can retry from the dashboard — properties will sync when credentials are verified.\n\n"
                )
            else:
                note = f"I found **{properties_found} properties**. They'll sync in the background.\n\n"

            return OnboardingResponse(
                message=(
                    f"{'✅' if not connect_error else '⚠️'} {pms_name} credentials saved!\n\n"
                    + note +
                    f"Now let's capture your policies so {session.concierge_name} "
                    f"can give accurate answers."
                ),
                step=OnboardingStep.POLICIES,
                progress_percent=55,
                show_input=True,
                action_buttons=[
                    {"id": "start_policies", "label": "Let's do it!"},
                ],
            )
        
        elif session.pending_question == "website_url":
            website_url = user_input.strip()
            session.policies["_website_url"] = website_url

            # Real website scrape via property_enrichment_scraper logic
            scraped_props: list = []
            scrape_error: str | None = None

            try:
                import httpx as _httpx
                from bs4 import BeautifulSoup as _BS

                async with _httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(website_url)
                    resp.raise_for_status()
                    soup = _BS(resp.text, "lxml")

                    # Strategy 1: look for structured JSON-LD property listings
                    for script in soup.find_all("script", type="application/ld+json"):
                        import json as _json
                        try:
                            data = _json.loads(script.string or "{}")
                            items = data if isinstance(data, list) else [data]
                            for item in items:
                                if item.get("@type") in ("LodgingBusiness", "VacationRental", "Accommodation"):
                                    scraped_props.append({
                                        "name": item.get("name", ""),
                                        "address": item.get("address", {}).get("streetAddress", ""),
                                        "description": item.get("description", "")[:500],
                                        "url": item.get("url", website_url),
                                    })
                        except Exception:
                            pass

                    # Strategy 2: look for common rental listing patterns in HTML
                    if not scraped_props:
                        for card in soup.select(
                            ".property-card, .listing-card, .unit-card, "
                            "[class*='property'], [class*='listing'], [class*='rental']"
                        )[:40]:
                            name_el = card.select_one("h2, h3, .property-name, .title")
                            if name_el:
                                scraped_props.append({
                                    "name": name_el.get_text(strip=True),
                                    "url": website_url,
                                })

            except ImportError:
                scrape_error = "httpx/BeautifulSoup not installed — install to enable website scraping."
            except Exception as exc:
                logger.warning("[Onboarding] website scrape failed: %s", exc)
                scrape_error = str(exc)[:120]

            # Stash scraped properties for PropertyImportService in PROPERTIES step
            session.policies["_scraped_properties"] = scraped_props
            session.properties_found = len(scraped_props)
            session.completed_steps.append(OnboardingStep.INTEGRATION)
            session.current_step = OnboardingStep.POLICIES

            if scrape_error:
                result_msg = (
                    f"⚠️ Couldn't scrape {website_url} automatically ({scrape_error}).\n"
                    f"You can import properties manually from your dashboard after onboarding."
                )
            elif scraped_props:
                result_msg = (
                    f"🔍 Analyzed **{website_url}**\n\n"
                    f"Found **{len(scraped_props)} properties**. "
                    f"I'll need you to verify the data — let's capture your policies first."
                )
            else:
                result_msg = (
                    f"🔍 Analyzed **{website_url}** — couldn't auto-detect properties from the page structure.\n\n"
                    f"You can import properties manually from your dashboard. Let's capture policies first."
                )

            return OnboardingResponse(
                message=result_msg,
                step=OnboardingStep.POLICIES,
                progress_percent=55,
                show_input=True,
                action_buttons=[
                    {"id": "start_policies", "label": "Continue"},
                    {"id": "retry_scrape",  "label": "Try a different URL"},
                ],
            )
        
        elif session.pending_question == "files_directory":
            files_directory = user_input.strip()

            # ── Real MCP file scan ──────────────────────────────────────────
            # Launch the str-data-collector MCP server via subprocess and
            # call scan_directory + batch_analyze to get real counts.
            scan_result = await _run_mcp_file_scan(
                directory=files_directory,
                operator_id=session.operator_id or session.session_id,
            )

            session.properties_found  = scan_result["properties_found"]
            session.documents_indexed = scan_result["documents_scanned"]
            # Stash the raw extracted data so knowledge-base step can index it
            session.policies["_file_scan_result"] = scan_result

            session.completed_steps.append(OnboardingStep.INTEGRATION)
            session.current_step = OnboardingStep.POLICIES

            wifi_count  = scan_result.get("wifi_found", 0)
            code_count  = scan_result.get("codes_found", 0)
            sheet_count = scan_result.get("spreadsheets", 0)
            doc_count   = scan_result.get("documents", 0)
            pdf_count   = scan_result.get("pdfs", 0)
            err_note    = f"\n\n⚠️ {scan_result['error']}" if scan_result.get("error") else ""

            return OnboardingResponse(
                message=(
                    f"📁 **Scanned {files_directory}**\n\n"
                    f"Files found:\n"
                    f"• {sheet_count} spreadsheets (property lists, rates)\n"
                    f"• {doc_count} Word / text documents (house manuals)\n"
                    f"• {pdf_count} PDFs (welcome guides)\n\n"
                    f"Extracted data for **{session.properties_found} properties**:\n"
                    f"• WiFi credentials: {wifi_count} properties\n"
                    f"• Door / gate codes: {code_count} properties\n"
                    f"• Check-in/out times: {session.properties_found} properties\n\n"
                    f"I'll verify this with you later. Let's capture your policies now."
                    f"{err_note}"
                ),
                step=OnboardingStep.POLICIES,
                progress_percent=55,
                show_input=True,
                action_buttons=[
                    {"id": "start_policies", "label": "Continue"},
                    {"id": "review_data",    "label": "Review extracted data first"},
                ],
            )
        
        return self._unknown_input_response(session)
    
    async def _handle_policies(
        self,
        session: OnboardingSession,
        user_input: str,
    ) -> OnboardingResponse:
        """Handle POLICIES step - policy questionnaire."""
        from app.services.agents.onboarding.policy_questionnaire import PolicyQuestionnaire
        
        questionnaire = PolicyQuestionnaire()
        return await questionnaire.handle_input(session, user_input, self)
    
    async def _start_policies(self, session: OnboardingSession) -> OnboardingResponse:
        """Start the policy questionnaire."""
        from app.services.agents.onboarding.policy_questionnaire import PolicyQuestionnaire
        
        questionnaire = PolicyQuestionnaire()
        return questionnaire.get_first_question(session)
    
    async def _handle_properties(
        self,
        session: OnboardingSession,
        user_input: str,
    ) -> OnboardingResponse:
        """
        PROPERTIES step — import extracted data into the canonical `properties`
        table and surface a coverage report so the operator can see exactly
        what's missing before going live.

        Sources (in priority order):
          1. MCP file scan result  (stashed in session.policies["_file_scan_result"])
          2. PMS listings          (if session.pms_connected)
          3. Widget scrape         (if session.integration_type == "scraper")
        """
        import_errors: list = []
        total_imported = 0

        if session.operator_id:
            try:
                from app.services.property_import_service import PropertyImportService
                svc = PropertyImportService(self.db)

                # ── 1. File scan ─────────────────────────────────────────
                scan_result = session.policies.get("_file_scan_result", {})
                if scan_result.get("property_database"):
                    res = await svc.import_from_file_scan(
                        operator_id=session.operator_id,
                        company_id=session.operator_id,
                        market_id=session.market_id,
                        scan_result=scan_result,
                    )
                    total_imported += res.total
                    import_errors.extend(res.errors)
                    logger.info(
                        "[Onboarding] file_scan import: inserted=%d updated=%d",
                        res.inserted, res.updated,
                    )

                # ── 2. PMS listings ──────────────────────────────────────
                if session.pms_connected and session.pms_provider:
                    try:
                        pms_listings_raw = session.policies.get("_pms_listings", [])
                        if pms_listings_raw:
                            # Re-hydrate as CanonicalListing-like objects
                            from app.services.connectors.pms_connectors import CanonicalListing
                            listings_obj = []
                            for ld in pms_listings_raw:
                                try:
                                    listings_obj.append(CanonicalListing(**ld))
                                except Exception:
                                    # dict-like fallback: just pass dict through widget path
                                    listings_obj.append(type("_L", (), ld)())
                            res = await svc.import_from_pms_listings(
                                operator_id=session.operator_id,
                                company_id=session.operator_id,
                                market_id=session.market_id,
                                listings=listings_obj,
                            )
                            total_imported += res.total
                            import_errors.extend(res.errors)
                    except Exception as exc:
                        logger.warning("[Onboarding] PMS listing import error (non-fatal): %s", exc)

                # ── 3. Website-scraper properties ────────────────────────
                scraped_props = session.policies.get("_scraped_properties", [])
                if scraped_props and session.integration_type == "scraper":
                    try:
                        res = await svc.import_from_widget_scrape(
                            operator_id=session.operator_id,
                            company_id=session.operator_id,
                            market_id=session.market_id,
                            scraped_properties=scraped_props,
                        )
                        total_imported += res.total
                        import_errors.extend(res.errors)
                    except Exception as exc:
                        logger.warning("[Onboarding] widget scrape import error (non-fatal): %s", exc)

                # ── 3. Coverage report ───────────────────────────────────
                coverage = await svc.enrich_missing_fields(
                    operator_id=session.operator_id,
                    company_id=session.operator_id,
                )
                session.policies["_coverage_report"] = coverage

            except Exception as exc:
                logger.warning("[Onboarding] _handle_properties error (non-fatal): %s", exc)
                import_errors.append(str(exc))

        # ── Auto-infer market from property coordinates ────────────────────
        # If the operator selected "My market isn't listed" or we have an unknown
        # market, reverse-geocode their properties to detect the market automatically.
        if session.operator_id and (
            not session.market_id
            or session.market_id == "MARKET_UNKNOWN"
            or "MARKET_" not in session.market_id
        ):
            try:
                from app.services.knowledge.market_inference import infer_market_from_db
                inferred = await infer_market_from_db(
                    self.db, session.operator_id, session.market_id
                )
                if inferred.confidence >= 0.5:
                    session.market_id   = inferred.market_id
                    session.market_name = inferred.market_name
                    session.policies["_market_inferred"]   = True
                    session.policies["_market_confidence"] = inferred.confidence
                    logger.info(
                        "[Onboarding] Market inferred: %s (%.0f%% confidence)",
                        inferred.market_id, inferred.confidence * 100,
                    )
            except Exception as exc:
                logger.warning("[Onboarding] Market inference failed (non-fatal): %s", exc)

        # ── Auto-build event sources for new/unknown markets ────────────────
        # MarketScraperBuilder discovers official tourism event pages for any
        # city dynamically — no hardcoded lists needed.
        if session.market_id and session.market_id not in (
            "MARKET_30A", "MARKET_DESTIN", "MARKET_PCB",  # static curated markets
        ):
            try:
                from tools.market_scraper_builder import auto_build_for_new_market
                city  = (session.market_name or "").split(",")[0].strip()
                state = (session.market_name or "").split(",")[-1].strip() if "," in (session.market_name or "") else ""
                await auto_build_for_new_market(
                    market_id   = session.market_id,
                    market_name = session.market_name or city,
                    city        = city,
                    state       = state,
                )
                logger.info("[Onboarding] Event sources built for %s", session.market_id)
            except Exception as exc:
                logger.warning("[Onboarding] Market scraper builder failed (non-fatal): %s", exc)

        session.completed_steps.append(OnboardingStep.PROPERTIES)
        session.current_step = OnboardingStep.KNOWLEDGE_BASE

        coverage = session.policies.get("_coverage_report", {})
        total_props = coverage.get("total", session.properties_found)
        complete_props = coverage.get("complete", total_props)
        missing_fields = coverage.get("missing_by_field", {})

        # Build a human-readable gap summary
        gap_lines = []
        field_labels = {
            "wifi_network":  "WiFi network name",
            "wifi_password": "WiFi password",
            "door_code":     "Door code",
            "check_in_time": "Check-in time",
            "check_out_time":"Check-out time",
            "address_line1": "Street address",
            "bedrooms":      "Bedroom count",
            "bathrooms":     "Bathroom count",
        }
        for field, props_missing in missing_fields.items():
            label = field_labels.get(field, field)
            gap_lines.append(f"• {label}: missing for {len(props_missing)} propert{'y' if len(props_missing)==1 else 'ies'}")

        gap_section = ""
        if gap_lines:
            gap_section = (
                f"\n\n⚠️ **Data gaps found** (you can fill these later):\n"
                + "\n".join(gap_lines[:6])
            )

        err_note = ""
        if import_errors:
            err_note = f"\n\n⚠️ {len(import_errors)} propert{'y' if len(import_errors)==1 else 'ies'} had import errors — check logs."

        return OnboardingResponse(
            message=(
                f"✅ **Properties imported to database!**\n\n"
                f"• **{total_props}** total properties\n"
                f"• **{complete_props}** fully complete (all key fields)\n"
                f"• **{total_props - complete_props}** with gaps to fill"
                f"{gap_section}{err_note}\n\n"
                f"Building your knowledge base now..."
            ),
            step=OnboardingStep.KNOWLEDGE_BASE,
            progress_percent=85,
            show_input=False,
            action_buttons=[
                {"id": "build_kb",       "label": "Build Knowledge Base"},
                {"id": "fill_gaps_later","label": "I'll fill gaps later"},
            ],
        )
    
    async def _handle_knowledge_base(
        self,
        session: OnboardingSession,
        user_input: str,
    ) -> OnboardingResponse:
        """
        KNOWLEDGE_BASE step.

        Vector-store documents are now derived exclusively from the canonical
        `properties` DB rows written by _handle_properties() via
        PropertyImportService.  We no longer write to knowledge_embeddings
        directly here — that would create a parallel, unsynchronised copy.

        What this step does:
          1. Calls KnowledgeIndexer.index_local_area() for dining/activities/beach
          2. Re-indexes all properties already in the DB for this operator
             (picks up any that were imported before this session too)
          3. Indexes operator policies from the questionnaire
        """
        indexed = 0
        operator_id = session.operator_id or session.session_id

        try:
            from app.services.knowledge.knowledge_indexer import KnowledgeIndexer

            indexer = KnowledgeIndexer(self.db)

            # ── 0. Seed local market data via Places API (large cities) ──
            from app.services.knowledge.places_pipeline import PlacesPipeline, is_large_city_market
            if is_large_city_market(session.market_id or ""):
                pipeline = PlacesPipeline()
                if pipeline.is_available():
                    # Derive operator centroid from properties or use market default
                    op_lat, op_lng = await _get_operator_centroid(
                        self.db, operator_id, session.market_id
                    )
                    seed_result = await pipeline.seed_market(
                        market_id=session.market_id,
                        operator_id=operator_id,
                        operator_geofence_lat=op_lat,
                        operator_geofence_lng=op_lng,
                        radius_km=3.0,
                        db_session=self.db,
                    )
                    indexed += seed_result.places_indexed
                    logger.info(
                        "[Onboarding] Places API seed: %d places for %s",
                        seed_result.places_indexed, session.market_id,
                    )
                else:
                    logger.warning(
                        "[Onboarding] GOOGLE_PLACES_API_KEY not set — "
                        "local area knowledge will be limited for %s", session.market_id,
                    )

            # ── 0b. Discover hyper-local neighborhood event sources ─────────
            # Uses the LLM to find BIDs, arts districts, community calendars
            # for each neighborhood relevant to this operator's properties.
            # Runs once per neighborhood, results cached permanently.
            try:
                from app.mcp.registry import get_mcp_registry
                from app.services.knowledge.places_pipeline import (
                    MARKET_REGISTRY, get_neighborhood_for_coords,
                )
                registry = get_mcp_registry()
                # Inject DB session into the neighborhood_intel server
                ni_server = registry._servers.get("neighborhood_intel")
                if ni_server:
                    ni_server.set_db_session(self.db)

                market_def = MARKET_REGISTRY.get(session.market_id or "")
                neighborhoods_to_scan = []

                if market_def and market_def.is_large_city:
                    # Find the closest neighborhood(s) to operator's centroid
                    hood = get_neighborhood_for_coords(
                        session.market_id, op_lat, op_lng
                    )
                    if hood:
                        neighborhoods_to_scan.append(hood)
                elif session.market_name:
                    # Small/unknown market — treat the city itself as a neighborhood
                    from app.services.knowledge.places_pipeline import Neighborhood
                    neighborhoods_to_scan.append(Neighborhood(
                        name=session.market_name.split(",")[0].strip(),
                        slug=(session.market_name.split(",")[0].strip()
                              .lower().replace(" ", "_")),
                        center_lat=op_lat,
                        center_lng=op_lng,
                        radius_km=5.0,
                    ))

                city_name = (
                    session.market_name.split(",")[0].strip()
                    if session.market_name else "Unknown"
                )
                for hood in neighborhoods_to_scan:
                    disc_result = await registry.call(
                        "neighborhood_intel",
                        "discover_neighborhood_sources",
                        operator_id,
                        {
                            "neighborhood": hood.name,
                            "city":         city_name,
                            "market_id":    session.market_id,
                            "lat":          hood.center_lat,
                            "lng":          hood.center_lng,
                            "market_type":  market_def.market_type if market_def else "city",
                        },
                    )
                    if disc_result.success:
                        validated = disc_result.data.get("sources_validated", 0)
                        logger.info(
                            "[Onboarding] Neighborhood intel: %d sources for %s",
                            validated, hood.name,
                        )
                        # Immediately scrape events from discovered sources
                        if validated > 0:
                            await registry.call(
                                "neighborhood_intel",
                                "get_neighborhood_events",
                                operator_id,
                                {
                                    "neighborhood_slug": hood.slug,
                                    "market_id":         session.market_id,
                                    "operator_id":       operator_id,
                                    "days_ahead":        90,
                                },
                            )
            except Exception as exc:
                logger.warning(
                    "[Onboarding] Neighborhood intel failed (non-fatal): %s", exc
                )

            # ── 1. Local area (dining, activities, beach access) ─────────
            local_result = await indexer.index_local_area(
                operator_id=operator_id,
            )
            indexed += local_result.documents_indexed + local_result.documents_updated
            logger.info(
                "[Onboarding] local area indexed: %d docs for %s",
                local_result.documents_indexed, operator_id,
            )

            # ── 2. Re-index all properties in the DB for this operator ───
            from sqlalchemy import text as _text
            rows = await self.db.execute(
                _text("""
                    SELECT internal_code, name, address_line1, city, state,
                           bedrooms, bathrooms, sleeps, amenities, description,
                           extra_data
                    FROM properties
                    WHERE tenant_id = :op AND deleted_at IS NULL
                """),
                {"op": operator_id},
            )
            props = rows.mappings().all()

            for p in props:
                extra = p.get("extra_data") or {}
                amenities = p.get("amenities") or {}
                code = p.get("internal_code") or p.get("name", "")

                prop_data = {
                    "name": p.get("name", code),
                    "address": p.get("address_line1", ""),
                    "community": p.get("city", ""),
                    "bedrooms": p.get("bedrooms"),
                    "bathrooms": p.get("bathrooms"),
                    "sleeps": p.get("sleeps"),
                    "description": p.get("description"),
                    # Operational fields from extra_data
                    "wifi_network":  extra.get("wifi_network"),
                    "wifi_password": extra.get("wifi_password"),
                    "door_code":     extra.get("door_code"),
                    "gate_code":     extra.get("gate_code"),
                    "check_in_time": extra.get("check_in_time", "4:00 PM"),
                    "check_out_time":extra.get("check_out_time", "11:00 AM"),
                    # Amenity flags
                    "has_pool":    bool(amenities.get("pool")),
                    "pool_heated": (amenities.get("pool") or {}).get("heated", False),
                    "has_hot_tub": bool(amenities.get("hot_tub")),
                    "pet_friendly": bool(amenities.get("pet_friendly")),
                    "beach_gear":   bool(amenities.get("beach_gear")),
                    "has_grill":    bool(amenities.get("grill")),
                }
                try:
                    prop_result = await indexer.index_property(
                        operator_id=operator_id,
                        property_code=code,
                        property_data=prop_data,
                    )
                    indexed += prop_result.documents_indexed + prop_result.documents_updated
                except Exception as exc:
                    logger.warning(
                        "[Onboarding] property index failed for %s (non-fatal): %s", code, exc
                    )

            # ── 3. Index operator policies ───────────────────────────────
            policies = {k: v for k, v in session.policies.items() if not k.startswith("_")}
            if policies:
                try:
                    from app.mcp.registry import get_mcp_registry
                    registry = get_mcp_registry()
                    import json as _json
                    policy_doc = "Operator policies:\n" + "\n".join(
                        f"• {k}: {v}" for k, v in policies.items()
                    )
                    await registry.call(
                        "knowledge", "index_document", operator_id,
                        {
                            "content": policy_doc,
                            "doc_type": "operator_policy",
                            "source": "onboarding",
                        },
                    )
                    indexed += 1
                except Exception as exc:
                    logger.warning("[Onboarding] policy index failed (non-fatal): %s", exc)

        except Exception as exc:
            logger.warning("[Onboarding] KB build error (non-fatal): %s", exc)

        session.documents_indexed = max(indexed, session.documents_indexed)
        session.completed_steps.append(OnboardingStep.KNOWLEDGE_BASE)
        session.current_step = OnboardingStep.ACTIVATION

        return OnboardingResponse(
            message=(
                f"✅ **Knowledge base ready!**\n\n"
                f"**{session.documents_indexed}** documents indexed:\n"
                f"• Property details, WiFi, door codes\n"
                f"• Local restaurants and activities\n"
                f"• Your policies and FAQs\n\n"
                f"{session.concierge_emoji} **{session.concierge_name}** is ready to help your guests!"
            ),
            step=OnboardingStep.ACTIVATION,
            progress_percent=95,
            show_input=False,
            action_buttons=[
                {"id": "activate",    "label": "Activate Concierge"},
                {"id": "test_first",  "label": "Test with sample conversation"},
            ],
        )
    
    async def _handle_activation(
        self,
        session: OnboardingSession,
        user_input: str,
    ) -> OnboardingResponse:
        """Handle ACTIVATION step - final activation."""
        session.completed_steps.append(OnboardingStep.ACTIVATION)
        session.current_step = OnboardingStep.COMPLETED
        session.completed_at = datetime.utcnow()
        
        return OnboardingResponse(
            message=f"🎉 **Congratulations!** Your concierge is live!\n\n"
                   f"**{session.concierge_emoji} {session.concierge_name}** - {session.company_name} Concierge\n"
                   f"📍 {session.market_name}\n"
                   f"🏠 {session.properties_found} properties\n\n"
                   f"**Dashboard:** https://dashboard.{session.company_code.lower()}.concierge.ai\n"
                   f"**Guest links:** https://c.{session.company_code.lower()}.concierge.ai/{{token}}\n\n"
                   f"Next steps:\n"
                   f"• Send welcome SMS to current guests\n"
                   f"• Add concierge links to booking confirmations\n"
                   f"• Monitor conversations in your dashboard",
            step=OnboardingStep.COMPLETED,
            progress_percent=100,
            is_complete=True,
            show_input=False,
            action_buttons=[
                {"id": "view_dashboard", "label": "View Dashboard"},
                {"id": "send_welcome", "label": "Send Welcome to Guests"},
            ],
        )
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _get_welcome_message(self) -> str:
        """Generate welcome message."""
        return (
            "👋 **Welcome to Concierge Setup!**\n\n"
            "I'll help you set up your AI-powered guest concierge in about 10 minutes.\n\n"
            "Here's what we'll cover:\n"
            "1. Company basics & branding\n"
            "2. Connect your property data\n"
            "3. Capture your policies\n"
            "4. Activate your concierge\n\n"
            "Let's start! **What's your company name?**"
        )
    
    def _generate_code(self, name: str) -> str:
        """Generate a short code from company name."""
        words = name.split()
        if len(words) >= 2:
            return "".join(w[0].upper() for w in words[:2])
        return name[:2].upper()
    
    def _create_response(
        self,
        session: OnboardingSession,
        message: str,
        **kwargs,
    ) -> OnboardingResponse:
        """Helper to create response with session context."""
        progress = int(len(session.completed_steps) / len(OnboardingStep) * 100)
        
        return OnboardingResponse(
            message=message,
            step=session.current_step,
            progress_percent=progress,
            **kwargs,
        )
    
    def _unknown_input_response(self, session: OnboardingSession) -> OnboardingResponse:
        """Response for unexpected input."""
        return self._create_response(
            session,
            "I'm not sure what you mean. Could you try again?",
            show_input=True,
        )


# =============================================================================
# MCP FILE SCAN HELPER
# =============================================================================

async def _run_mcp_file_scan(directory: str, operator_id: str) -> dict:
    """
    Launch the str-data-collector MCP server as a subprocess, call
    scan_directory + batch_analyze + build_property_database, and return
    a summary dict that the onboarding agent renders to the operator.

    Falls back gracefully if Node / the MCP server is unavailable.

    Return shape:
        {
          "properties_found":  int,
          "documents_scanned": int,
          "spreadsheets":      int,
          "documents":         int,
          "pdfs":              int,
          "wifi_found":        int,
          "codes_found":       int,
          "property_database": dict | None,   # raw build_property_database output
          "error":             str | None,
        }
    """
    import asyncio
    import json
    import os
    import shutil
    from pathlib import Path

    MCP_SERVER_PATH = Path(__file__).parent.parent.parent.parent.parent / \
        "mcp_servers" / "str-data-collector" / "src" / "index.js"

    result: dict = {
        "properties_found":  0,
        "documents_scanned": 0,
        "spreadsheets":      0,
        "documents":         0,
        "pdfs":              0,
        "wifi_found":        0,
        "codes_found":       0,
        "property_database": None,
        "error":             None,
    }

    # ── Prerequisite check ─────────────────────────────────────────────────
    if not shutil.which("node"):
        result["error"] = "Node.js not found — file scan skipped. Install Node ≥18 to enable."
        return result
    if not MCP_SERVER_PATH.exists():
        result["error"] = f"MCP server not found at {MCP_SERVER_PATH}"
        return result

    async def _call_tool(proc, tool_name: str, args: dict) -> dict:
        """Send one MCP tool call over stdin and read the response from stdout."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }
        payload = json.dumps(request) + "\n"
        proc.stdin.write(payload.encode())
        await proc.stdin.drain()
        raw = await asyncio.wait_for(proc.stdout.readline(), timeout=60)
        resp = json.loads(raw.decode())
        content = resp.get("result", {}).get("content", [{}])
        text = content[0].get("text", "{}")
        return json.loads(text)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", str(MCP_SERVER_PATH),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ},
        )

        # 1. scan_directory
        scan = await _call_tool(proc, "scan_directory", {"path": directory})
        if scan.get("error"):
            result["error"] = scan["error"]
            proc.terminate()
            return result

        spreadsheets = scan.get("spreadsheets", [])
        documents    = scan.get("documents", [])
        all_files    = spreadsheets + documents

        result["spreadsheets"] = len(spreadsheets)
        result["documents"]    = len([f for f in documents if f.endswith(".docx") or f.endswith(".doc")])
        result["pdfs"]         = len([f for f in documents if f.endswith(".pdf")])
        result["documents_scanned"] = len(all_files)

        if not all_files:
            result["error"] = "No property files found in that directory."
            proc.terminate()
            return result

        # 2. batch_analyze (cap at 100 files so onboarding stays snappy)
        batch = await _call_tool(proc, "batch_analyze", {
            "paths":    all_files[:100],
            "maxFiles": 100,
        })
        analyzed = batch.get("results", [])

        # 3. build_property_database
        db_result = await _call_tool(proc, "build_property_database", {
            "analyzedFiles": analyzed,
            "operatorId":    operator_id,
        })
        result["property_database"] = db_result

        props = db_result.get("properties", [])
        result["properties_found"] = len(props)
        result["wifi_found"]  = sum(1 for p in props if p.get("wifi_network"))
        result["codes_found"] = sum(1 for p in props if p.get("door_code") or p.get("gate_code"))

        proc.terminate()

    except asyncio.TimeoutError:
        result["error"] = "File scan timed out (>60 s). Try a smaller directory."
    except Exception as exc:
        result["error"] = f"File scan error: {exc}"
        logger.warning(f"[MCP file scan] {exc}")

    return result


# =============================================================================
# Operator centroid helper
# =============================================================================

async def _get_operator_centroid(
    db_session,
    operator_id: str,
    market_id: Optional[str],
) -> tuple[float, float]:
    """
    Return the lat/lng centroid of an operator's properties.
    Falls back to the market's first neighborhood center if no properties found.
    """
    from app.services.knowledge.places_pipeline import MARKET_REGISTRY
    try:
        from sqlalchemy import text as _text
        result = await db_session.execute(
            _text("""
                SELECT AVG(latitude) AS lat, AVG(longitude) AS lng
                FROM properties
                WHERE tenant_id = :op
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND deleted_at IS NULL
            """),
            {"op": operator_id},
        )
        row = result.fetchone()
        if row and row[0] is not None:
            return float(row[0]), float(row[1])
    except Exception:
        pass

    # Fallback: use first neighborhood center for this market
    market = MARKET_REGISTRY.get(market_id or "")
    if market and market.neighborhoods:
        hood = market.neighborhoods[0]
        return hood.center_lat, hood.center_lng

    # Hard fallback: Miami Brickell
    return 25.760, -80.195


# =============================================================================
# Singleton
# =============================================================================
_onboarding_agent: Optional[OnboardingAgent] = None


async def get_onboarding_agent(db_session: AsyncSession) -> OnboardingAgent:
    """Get or create onboarding agent."""
    global _onboarding_agent
    if _onboarding_agent is None:
        _onboarding_agent = OnboardingAgent(db_session)
    return _onboarding_agent
