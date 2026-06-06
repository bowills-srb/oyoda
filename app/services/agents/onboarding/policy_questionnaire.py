"""
Policy Questionnaire - Captures operator-specific policies.

This is the structured questionnaire that captures:
- Check-in/out policies
- Discount policies
- Pet policies
- Pool heat, beach chairs
- And more...

The captured data is stored and used by the Voice Pod
to give accurate, operator-specific answers.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agents.onboarding.onboarding_agent import (
        OnboardingAgent,
        OnboardingSession,
        OnboardingResponse,
        OnboardingStep,
    )


class QuestionCategory(str, Enum):
    """Categories of policy questions."""
    CHECK_IN_OUT = "check_in_out"
    LATE_CHECKOUT = "late_checkout"
    EARLY_CHECKIN = "early_checkin"
    CANCELLATION = "cancellation"
    DISCOUNTS = "discounts"
    PETS = "pets"
    POOL_HEAT = "pool_heat"
    BEACH_CHAIRS = "beach_chairs"
    SUPPORT = "support"


@dataclass
class PolicyQuestion:
    """A single policy question."""
    id: str
    category: QuestionCategory
    question: str
    input_type: str  # text, select, boolean, number
    options: Optional[List[Dict[str, str]]] = None
    placeholder: Optional[str] = None
    default: Optional[Any] = None
    required: bool = True
    depends_on: Optional[Dict[str, Any]] = None  # Show only if condition met
    help_text: Optional[str] = None


class PolicyQuestionnaire:
    """
    Manages the policy questionnaire flow.
    
    Questions are organized by category and asked in sequence.
    Some questions depend on previous answers (e.g., late checkout fee
    only asked if late checkout is available).
    """
    
    # All policy questions in order
    QUESTIONS: List[PolicyQuestion] = [
        # Check-in/out
        PolicyQuestion(
            id="check_in_time",
            category=QuestionCategory.CHECK_IN_OUT,
            question="What time is check-in?",
            input_type="select",
            options=[
                {"value": "2:00 PM", "label": "2:00 PM"},
                {"value": "3:00 PM", "label": "3:00 PM"},
                {"value": "4:00 PM", "label": "4:00 PM"},
                {"value": "5:00 PM", "label": "5:00 PM"},
            ],
            default="4:00 PM",
        ),
        PolicyQuestion(
            id="check_out_time",
            category=QuestionCategory.CHECK_IN_OUT,
            question="What time is check-out?",
            input_type="select",
            options=[
                {"value": "9:00 AM", "label": "9:00 AM"},
                {"value": "10:00 AM", "label": "10:00 AM"},
                {"value": "11:00 AM", "label": "11:00 AM"},
                {"value": "12:00 PM", "label": "12:00 PM"},
            ],
            default="10:00 AM",
        ),
        
        # Late checkout
        PolicyQuestion(
            id="late_checkout_available",
            category=QuestionCategory.LATE_CHECKOUT,
            question="Do you offer late checkout?",
            input_type="boolean",
            default=True,
        ),
        PolicyQuestion(
            id="late_checkout_max_time",
            category=QuestionCategory.LATE_CHECKOUT,
            question="Latest checkout time?",
            input_type="select",
            options=[
                {"value": "12:00 PM", "label": "12:00 PM (Noon)"},
                {"value": "1:00 PM", "label": "1:00 PM"},
                {"value": "2:00 PM", "label": "2:00 PM"},
                {"value": "3:00 PM", "label": "3:00 PM"},
            ],
            default="2:00 PM",
            depends_on={"late_checkout_available": True},
        ),
        PolicyQuestion(
            id="late_checkout_fee",
            category=QuestionCategory.LATE_CHECKOUT,
            question="Late checkout fee?",
            input_type="number",
            placeholder="50",
            default=50,
            depends_on={"late_checkout_available": True},
            help_text="Enter 0 if free",
        ),
        
        # Discounts
        PolicyQuestion(
            id="discount_last_minute_enabled",
            category=QuestionCategory.DISCOUNTS,
            question="Do you offer last-minute discounts?",
            input_type="boolean",
            default=True,
        ),
        PolicyQuestion(
            id="discount_last_minute_days",
            category=QuestionCategory.DISCOUNTS,
            question="How many days before is 'last-minute'?",
            input_type="select",
            options=[
                {"value": "3", "label": "3 days"},
                {"value": "5", "label": "5 days"},
                {"value": "7", "label": "7 days"},
                {"value": "14", "label": "14 days"},
            ],
            default="7",
            depends_on={"discount_last_minute_enabled": True},
        ),
        PolicyQuestion(
            id="discount_last_minute_percent",
            category=QuestionCategory.DISCOUNTS,
            question="Last-minute discount percent?",
            input_type="select",
            options=[
                {"value": "10", "label": "10%"},
                {"value": "15", "label": "15%"},
                {"value": "20", "label": "20%"},
                {"value": "25", "label": "25%"},
            ],
            default="15",
            depends_on={"discount_last_minute_enabled": True},
        ),
        PolicyQuestion(
            id="discount_long_stay_enabled",
            category=QuestionCategory.DISCOUNTS,
            question="Do you offer long-stay discounts?",
            input_type="boolean",
            default=True,
        ),
        PolicyQuestion(
            id="discount_long_stay_nights",
            category=QuestionCategory.DISCOUNTS,
            question="Minimum nights for long-stay discount?",
            input_type="select",
            options=[
                {"value": "5", "label": "5 nights"},
                {"value": "7", "label": "7 nights"},
                {"value": "14", "label": "14 nights"},
                {"value": "28", "label": "28 nights"},
            ],
            default="7",
            depends_on={"discount_long_stay_enabled": True},
        ),
        PolicyQuestion(
            id="discount_long_stay_percent",
            category=QuestionCategory.DISCOUNTS,
            question="Long-stay discount percent?",
            input_type="select",
            options=[
                {"value": "5", "label": "5%"},
                {"value": "10", "label": "10%"},
                {"value": "15", "label": "15%"},
                {"value": "20", "label": "20%"},
            ],
            default="10",
            depends_on={"discount_long_stay_enabled": True},
        ),
        
        # Pets
        PolicyQuestion(
            id="pets_allowed",
            category=QuestionCategory.PETS,
            question="What's your pet policy?",
            input_type="select",
            options=[
                {"value": "no", "label": "No pets allowed"},
                {"value": "some_properties", "label": "Some properties allow pets"},
                {"value": "yes", "label": "All properties allow pets"},
            ],
            default="no",
        ),
        PolicyQuestion(
            id="pet_fee",
            category=QuestionCategory.PETS,
            question="Pet fee?",
            input_type="number",
            placeholder="150",
            default=150,
            depends_on={"pets_allowed": ["yes", "some_properties"]},
        ),
        PolicyQuestion(
            id="pet_max_weight",
            category=QuestionCategory.PETS,
            question="Maximum pet weight (lbs)?",
            input_type="number",
            placeholder="50",
            default=50,
            depends_on={"pets_allowed": ["yes", "some_properties"]},
            required=False,
        ),
        
        # Pool heat
        PolicyQuestion(
            id="pool_heat_available",
            category=QuestionCategory.POOL_HEAT,
            question="Do any properties have pool heat available?",
            input_type="boolean",
            default=True,
        ),
        PolicyQuestion(
            id="pool_heat_fee",
            category=QuestionCategory.POOL_HEAT,
            question="Pool heat daily fee?",
            input_type="number",
            placeholder="50",
            default=50,
            depends_on={"pool_heat_available": True},
        ),
        PolicyQuestion(
            id="pool_heat_notice",
            category=QuestionCategory.POOL_HEAT,
            question="How much advance notice for pool heat?",
            input_type="select",
            options=[
                {"value": "24", "label": "24 hours"},
                {"value": "48", "label": "48 hours"},
                {"value": "72", "label": "72 hours"},
            ],
            default="48",
            depends_on={"pool_heat_available": True},
        ),
        
        # Beach chairs
        PolicyQuestion(
            id="beach_chairs_included",
            category=QuestionCategory.BEACH_CHAIRS,
            question="Are beach chairs/gear included?",
            input_type="boolean",
            default=False,
        ),
        PolicyQuestion(
            id="beach_chair_rental_info",
            category=QuestionCategory.BEACH_CHAIRS,
            question="Beach chair rental info (company name and phone)?",
            input_type="text",
            placeholder="La Dolce Vita (850-267-1444)",
            depends_on={"beach_chairs_included": False},
            required=False,
        ),
        
        # Support
        PolicyQuestion(
            id="support_phone",
            category=QuestionCategory.SUPPORT,
            question="What's your guest support phone number?",
            input_type="text",
            placeholder="(850) 555-0123",
        ),
        PolicyQuestion(
            id="support_email",
            category=QuestionCategory.SUPPORT,
            question="Support email?",
            input_type="text",
            placeholder="hello@yourcompany.com",
            required=False,
        ),
    ]
    
    def __init__(self):
        self._current_question_index = 0
    
    def get_first_question(self, session: "OnboardingSession") -> "OnboardingResponse":
        """Get the first policy question."""
        from app.services.agents.onboarding.onboarding_agent import OnboardingResponse, OnboardingStep
        
        session.pending_question = "policy_0"
        session.pending_question_type = "policy"
        
        q = self.QUESTIONS[0]
        
        return OnboardingResponse(
            message=f"📋 **Policy Questionnaire**\n\n"
                   f"I'll ask about your policies so {session.concierge_name} "
                   f"can give accurate answers.\n\n"
                   f"**{q.question}**",
            step=OnboardingStep.POLICIES,
            progress_percent=55,
            show_input=True,
            input_type=q.input_type,
            input_options=q.options,
            input_placeholder=q.placeholder,
        )
    
    async def handle_input(
        self,
        session: "OnboardingSession",
        user_input: str,
        agent: "OnboardingAgent",
    ) -> "OnboardingResponse":
        """Handle policy questionnaire input."""
        from app.services.agents.onboarding.onboarding_agent import OnboardingResponse, OnboardingStep
        
        # Parse current question index
        if session.pending_question and session.pending_question.startswith("policy_"):
            current_idx = int(session.pending_question.split("_")[1])
        else:
            current_idx = 0
        
        # Save the answer
        q = self.QUESTIONS[current_idx]
        value = self._parse_answer(q, user_input)
        session.policies[q.id] = value
        
        # Find next question (considering dependencies)
        next_idx = self._find_next_question(session, current_idx + 1)
        
        if next_idx is None:
            # Questionnaire complete
            session.completed_steps.append(OnboardingStep.POLICIES)
            session.current_step = OnboardingStep.PROPERTIES
            
            return OnboardingResponse(
                message="✅ **Policies captured!**\n\n"
                       f"I've saved your policies. {session.concierge_name} will use these "
                       f"to give accurate answers about:\n"
                       f"• Check-in/out times\n"
                       f"• Late checkout options\n"
                       f"• Discounts\n"
                       f"• Pet policies\n"
                       f"• And more!\n\n"
                       f"Now let's verify your property data.",
                step=OnboardingStep.PROPERTIES,
                progress_percent=75,
                show_input=False,
                action_buttons=[
                    {"id": "continue", "label": "Continue"},
                ],
            )
        
        # Ask next question
        next_q = self.QUESTIONS[next_idx]
        session.pending_question = f"policy_{next_idx}"
        
        # Calculate progress within policies (55-75%)
        progress = 55 + int((next_idx / len(self.QUESTIONS)) * 20)
        
        return OnboardingResponse(
            message=f"**{next_q.question}**",
            step=OnboardingStep.POLICIES,
            progress_percent=progress,
            show_input=True,
            input_type=next_q.input_type,
            input_options=next_q.options,
            input_placeholder=next_q.placeholder,
        )
    
    def _parse_answer(self, question: PolicyQuestion, user_input: str) -> Any:
        """Parse user input based on question type."""
        if question.input_type == "boolean":
            return user_input.lower() in ["yes", "true", "1", "y"]
        elif question.input_type == "number":
            try:
                return int(user_input.replace("$", "").replace(",", "").strip())
            except ValueError:
                return question.default or 0
        else:
            return user_input.strip()
    
    def _find_next_question(
        self,
        session: "OnboardingSession",
        start_idx: int,
    ) -> Optional[int]:
        """Find the next applicable question, considering dependencies."""
        for idx in range(start_idx, len(self.QUESTIONS)):
            q = self.QUESTIONS[idx]
            
            if q.depends_on:
                # Check if dependency is met
                for dep_key, dep_value in q.depends_on.items():
                    actual_value = session.policies.get(dep_key)
                    
                    if isinstance(dep_value, list):
                        if actual_value not in dep_value:
                            break  # Dependency not met, skip this question
                    elif actual_value != dep_value:
                        break  # Dependency not met, skip this question
                else:
                    # All dependencies met
                    return idx
            else:
                # No dependencies, this question is applicable
                return idx
        
        return None  # No more questions
    
    def get_policies_summary(self, session: "OnboardingSession") -> str:
        """Generate a summary of captured policies."""
        p = session.policies
        lines = []
        
        lines.append(f"• Check-in: {p.get('check_in_time', '4:00 PM')}")
        lines.append(f"• Check-out: {p.get('check_out_time', '10:00 AM')}")
        
        if p.get("late_checkout_available"):
            lines.append(f"• Late checkout: until {p.get('late_checkout_max_time')}, ${p.get('late_checkout_fee')} fee")
        
        if p.get("discount_last_minute_enabled"):
            lines.append(f"• Last-minute discount: {p.get('discount_last_minute_percent')}% within {p.get('discount_last_minute_days')} days")
        
        if p.get("discount_long_stay_enabled"):
            lines.append(f"• Long-stay discount: {p.get('discount_long_stay_percent')}% for {p.get('discount_long_stay_nights')}+ nights")
        
        pets = p.get("pets_allowed", "no")
        if pets == "yes":
            lines.append(f"• Pets: Allowed, ${p.get('pet_fee')} fee")
        elif pets == "some_properties":
            lines.append(f"• Pets: Some properties, ${p.get('pet_fee')} fee")
        else:
            lines.append("• Pets: Not allowed")
        
        if p.get("pool_heat_available"):
            lines.append(f"• Pool heat: ${p.get('pool_heat_fee')}/day, {p.get('pool_heat_notice')}hr notice")
        
        if p.get("beach_chairs_included"):
            lines.append("• Beach chairs: Included")
        elif p.get("beach_chair_rental_info"):
            lines.append(f"• Beach chairs: Rental from {p.get('beach_chair_rental_info')}")
        
        return "\n".join(lines)
