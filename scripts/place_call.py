"""Place an outbound call: create SIP participant + dispatch agent into the room."""
from __future__ import annotations
import asyncio
import json
import os
import uuid
from dotenv import load_dotenv
from livekit import api

load_dotenv()


async def main() -> None:
    call_id = f"spike-{uuid.uuid4().hex[:8]}"
    room_name = f"call-{call_id}"
    rep_phone = os.environ["TEST_REP_PHONE_NUMBER"]
    trunk_id = os.environ["LIVEKIT_SIP_TRUNK_ID"]

    lkapi = api.LiveKitAPI()
    try:
        # Dispatch the agent FIRST so it's waiting in the room when the SIP participant joins.
        dispatch = await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="ibv-spike",
                room=room_name,
                metadata=json.dumps({
                    "call_id": call_id,
                    "patients": ["patient-A", "patient-B"],
                }),
            )
        )
        print(f"Dispatched agent: {dispatch.id} to room {room_name}")

        # Dial out via SIP.
        sip = await lkapi.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk_id,
                sip_call_to=rep_phone,
                room_name=room_name,
                participant_identity="rep",
                participant_name="Insurance Rep (test)",
                wait_until_answered=True,
            )
        )
        print(f"SIP participant created: {sip.participant_identity} in {room_name}")
        print(f"Watch the call live: https://agents-playground.livekit.io/  → room {room_name}")
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
