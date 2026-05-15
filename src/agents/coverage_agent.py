from __future__ import annotations
from livekit.agents import function_tool, RunContext
from livekit.agents.voice import Agent

from src.agents.shared import CallUserData


class CoverageAgent(Agent):
    """Phase 2 (simulated): Coverage details for the next patient in queue."""

    def __init__(self, chat_ctx=None) -> None:
        super().__init__(
            instructions=(
                "You are still VERA, continuing the IBV call. You just transitioned to the COVERAGE segment for a NEW patient.\n"
                "The current patient's identifier is given to you in the per-turn instruction at segment start; refer to that patient by name throughout this segment.\n"
                "\n"
                "Briefly acknowledge the transition with one short phrase (e.g. 'Now moving to the next patient.'), then ask the rep these three questions about the current patient, ONE AT A TIME, waiting for an answer before moving on. Any short reply counts as an answer.\n"
                "  1. Coverage type — Individual or Family\n"
                "  2. Has the deductible been met for the year (yes / no)\n"
                "  3. In-network copay or coinsurance for primary care\n"
                "\n"
                "Rules:\n"
                "- One short sentence per turn. No chitchat, no summarizing.\n"
                "- After question 3 is answered, say 'Got it, thank you. Goodbye.' and IMMEDIATELY call the `end_call` tool.\n"
            ),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        userdata: CallUserData = self.session.userdata
        patient = userdata.advance_patient()
        if patient is None:
            await self.session.generate_reply(
                instructions="Say: 'No more patients. Thank you, goodbye.' then call end_call."
            )
            return
        await self.session.generate_reply(
            instructions=(
                f"Acknowledge the transition (one short phrase), then begin the coverage segment "
                f"for patient {patient}. Start with question 1 (coverage type — Individual or Family)."
            )
        )

    @function_tool()
    async def end_call(self, ctx: RunContext[CallUserData]) -> None:
        """End the call cleanly."""
        await self.session.aclose()
