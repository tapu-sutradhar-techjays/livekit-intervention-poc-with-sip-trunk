"""LiveKit agent worker. Registers as agent_name='ibv-spike', dispatched explicitly."""
from __future__ import annotations
import json
import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import AgentSession
from livekit.plugins import google, deepgram, cartesia, silero
from livekit.plugins.turn_detector.english import EnglishModel

from src.agents.basics_agent import BasicsAgent
from src.agents.shared import CallUserData

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ibv-spike")


async def entrypoint(ctx: JobContext) -> None:
    try:
        from src.tracing import init_tracing
        init_tracing()
    except ImportError:
        # Tracing extras (opentelemetry-*) not installed — skip silently.
        pass
    logger.info("Entrypoint received job %s, metadata=%s", ctx.job.id, ctx.job.metadata)
    await ctx.connect()

    metadata = json.loads(ctx.job.metadata or "{}")
    # Default queue keeps `console`-mode runs (no dispatch metadata) usable.
    userdata = CallUserData(
        call_id=metadata.get("call_id", ctx.job.id),
        patient_queue=metadata.get("patients") or ["patient-A", "patient-B"],
    )

    session: AgentSession[CallUserData] = AgentSession[CallUserData](
        userdata=userdata,
        vad=silero.VAD.load(),
        # Semantic end-of-turn detection cuts ~200-400ms off "user is done"
        # and reduces mid-sentence cutoffs vs. pure silence-threshold VAD.
        turn_detection=EnglishModel(),
        stt=deepgram.STT(model="nova-3"),
        # Vertex AI auth via Application Default Credentials (gcloud ADC).
        llm=google.LLM(model="gemini-2.5-flash", vertexai=True),
        tts=cartesia.TTS(voice="79a125e8-cd45-4c13-8a67-188112f4dd22"),
    )

    # Wait for the dialed rep (SIP participant) to actually answer before the
    # agent starts talking — otherwise BasicsAgent.on_enter greets an empty room
    # while the outbound call is still ringing (or was rejected, e.g. SIP 486 Busy).
    logger.info("Waiting for rep participant to join room %s", ctx.room.name)
    participant = await ctx.wait_for_participant(identity="rep")
    logger.info("Rep participant joined: %s", participant.identity)

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
