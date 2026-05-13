from __future__ import annotations
from livekit.agents import function_tool, RunContext
from livekit.agents.voice import Agent

from src.agents.shared import CallUserData


class CoverageAgent(Agent):
    """Phase 2 (simulated): Coverage details for next patient in queue."""

    def __init__(self, chat_ctx=None) -> None:
        super().__init__(
            instructions=(
                "You are still VERA. You have just transitioned to the coverage segment for a NEW patient.\n"
                "Briefly acknowledge the transition (e.g. 'Now moving to the next patient.'), then ask exactly ONE question:\n"
                "'What is the coverage type for {current_patient} — Individual or Family?'\n"
                "Wait for answer. Once they answer, say 'Got it, thank you. Goodbye.' and IMMEDIATELY call the `end_call` tool.\n"
                "Keep responses to ONE sentence."
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
            instructions=f"Transition smoothly and ask about coverage type for {patient}."
        )

    @function_tool()
    async def end_call(self, ctx: RunContext[CallUserData]) -> None:
        """End the call cleanly."""
        await self.session.aclose()
