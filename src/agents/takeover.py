"""RPC handlers that let the supervisor browser toggle AI mute/unmute."""
from __future__ import annotations
import logging
from livekit.agents.voice import AgentSession

from src.agents.shared import CallUserData

logger = logging.getLogger("ibv-spike.takeover")


def register_takeover_rpcs(session: AgentSession[CallUserData], local_participant) -> None:
    """Register RPCs on the agent's local participant.

    `local_participant` is `ctx.room.local_participant` from the entrypoint.
    """

    async def on_take_over(_data) -> str:
        logger.info("Supervisor TAKEOVER requested")
        session.input.set_audio_enabled(False)
        session.output.set_audio_enabled(False)
        session.output.set_transcription_enabled(False)
        session.interrupt()
        session.userdata.supervisor_in_control = True
        return "ok"

    async def on_hand_back(_data) -> str:
        logger.info("Supervisor HAND BACK requested")
        session.input.set_audio_enabled(True)
        session.output.set_audio_enabled(True)
        session.output.set_transcription_enabled(True)
        session.userdata.supervisor_in_control = False
        await session.generate_reply(
            instructions="Briefly acknowledge that you're resuming control: 'Okay, continuing.' Then proceed with the previous question."
        )
        return "ok"

    local_participant.register_rpc_method("supervisor/take-over", on_take_over)
    local_participant.register_rpc_method("supervisor/hand-back", on_hand_back)
