from __future__ import annotations
from livekit.agents import function_tool, RunContext
from livekit.agents.voice import Agent

from src.agents.shared import CallUserData


class BasicsAgent(Agent):
    """Phase 1 (simulated): Insurance Basics for the current patient."""

    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are VERA, an AI assistant making a TEST insurance benefits verification (IBV) call.\n"
                "The person on the line is a developer pretending to be an insurance rep.\n"
                "You are in the BASICS segment. The current patient's identifier is given to you in the per-turn instruction at segment start; refer to that patient by name throughout this segment.\n"
                "\n"
                "Ask the rep these three questions about the current patient, ONE AT A TIME, waiting for an answer before moving on. Any short reply (a value, yes/no, even 'let me check') counts as an answer — do not press for more detail.\n"
                "  1. Member ID on file\n"
                "  2. Date of birth on file\n"
                "  3. Group number on file\n"
                "\n"
                "Rules:\n"
                "- One short sentence per turn. No chitchat, no summarizing of prior answers.\n"
                "- After question 3 is answered, thank the rep briefly and IMMEDIATELY call the `next_segment` tool. Do NOT ask any further questions, do NOT recap.\n"
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
            instructions=(
                f"Greet the rep briefly (one short sentence), then begin the basics segment "
                f"for patient {patient}. Start with question 1 (Member ID on file)."
            )
        )

    @function_tool()
    async def next_segment(self, ctx: RunContext[CallUserData]) -> Agent:
        """Hand off to the coverage segment for the next patient."""
        # Lazy import to avoid circular deps.
        from src.agents.coverage_agent import CoverageAgent
        return CoverageAgent(chat_ctx=self.chat_ctx.copy(exclude_instructions=True))
