from __future__ import annotations
from livekit.agents import function_tool, RunContext
from livekit.agents.voice import Agent

from src.agents.shared import CallUserData


class BasicsAgent(Agent):
    """Phase 1 (simulated): Insurance Basics for current_patient."""

    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are VERA, an AI assistant doing a TEST call. The person on the line is a developer pretending to be an insurance rep.\n"
                "Your job for THIS segment: ask about ONE patient at a time. The current patient ID is in session userdata.\n"
                "Ask exactly ONE question: 'I'd like to verify insurance basics for {current_patient}. Are member ID and date of birth on file?'\n"
                "Wait for any short answer. Once they answer (yes/no/anything), thank them and IMMEDIATELY call the `next_segment` tool to hand off.\n"
                "Do not ask any other questions. Do not chitchat. Keep all responses to ONE sentence."
            ),
        )

    async def on_enter(self) -> None:
        userdata: CallUserData = self.session.userdata
        patient = userdata.advance_patient()
        if patient is None:
            await self.session.generate_reply(
                instructions="Say: 'No patients to process. Goodbye.' then stop."
            )
            return
        await self.session.generate_reply(
            instructions=f"Greet briefly and ask about patient {patient} per your instructions."
        )

    @function_tool()
    async def next_segment(self, ctx: RunContext[CallUserData]) -> Agent:
        """Hand off to the coverage segment for the next patient."""
        # Lazy import to avoid circular deps.
        from src.agents.coverage_agent import CoverageAgent
        return CoverageAgent(chat_ctx=self.chat_ctx.copy(exclude_instructions=True))
