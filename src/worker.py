"""LiveKit agent worker. Registers as agent_name='ibv-spike', dispatched explicitly."""
from __future__ import annotations
import json
import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import AgentSession
from livekit.plugins import openai, deepgram, cartesia, silero

from src.agents.basics_agent import BasicsAgent
from src.agents.shared import CallUserData

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ibv-spike")


async def entrypoint(ctx: JobContext) -> None:
    logger.info("Entrypoint received job %s, metadata=%s", ctx.job.id, ctx.job.metadata)
    await ctx.connect()

    metadata = json.loads(ctx.job.metadata or "{}")
    userdata = CallUserData(
        call_id=metadata.get("call_id", ctx.job.id),
        patient_queue=metadata.get("patients", []),
    )

    session: AgentSession[CallUserData] = AgentSession[CallUserData](
        userdata=userdata,
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(voice="79a125e8-cd45-4c13-8a67-188112f4dd22"),
    )

    await session.start(agent=BasicsAgent(), room=ctx.room)

    from src.agents.takeover import register_takeover_rpcs
    register_takeover_rpcs(session, ctx.room.local_participant)

    logger.info("Session started in room %s", ctx.room.name)

    # The session will run until the SIP participant disconnects or we explicitly close.


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="ibv-spike",
        )
    )
