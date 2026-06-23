"""HTTP API: issue supervisor tokens, place outbound calls from the frontend."""
from __future__ import annotations
import json
import os
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from livekit import api
from livekit.api.twirp_client import TwirpError
from pydantic import BaseModel

from src.server.tokens import supervisor_token

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlaceCallResponse(BaseModel):
    room: str
    supervisor_token: str
    livekit_url: str


@app.post("/place-call")
async def place_call() -> PlaceCallResponse:
    call_id = f"spike-{uuid.uuid4().hex[:8]}"
    room_name = f"call-{call_id}"
    lkapi = api.LiveKitAPI()
    try:
        await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name="ibv-spike",
                room=room_name,
                metadata=json.dumps({
                    "call_id": call_id,
                    "patients": ["patient-A", "patient-B"],
                }),
            )
        )
        # wait_until_answered=True so a failed dial (e.g. SIP 486 Busy, geo-blocked,
        # unverified number) raises here instead of being silently swallowed —
        # otherwise the agent sits in the room and /place-call lies with 200 OK.
        try:
            await lkapi.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=os.environ["LIVEKIT_SIP_TRUNK_ID"],
                    sip_call_to=os.environ["TEST_REP_PHONE_NUMBER"],
                    room_name=room_name,
                    participant_identity="rep",
                    participant_name="Insurance Rep (test)",
                    wait_until_answered=True,
                )
            )
        except TwirpError as e:
            # The dial failed — tear down the room so the dispatched agent doesn't
            # linger waiting for a rep that will never join.
            try:
                await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
            except TwirpError:
                pass
            sip_status = e.metadata.get("sip_status") if e.metadata else None
            detail = f"Call failed: {sip_status or e.message}"
            raise HTTPException(status_code=502, detail=detail) from e
    finally:
        await lkapi.aclose()
    return PlaceCallResponse(
        room=room_name,
        supervisor_token=supervisor_token(room_name, identity=f"sup-{uuid.uuid4().hex[:6]}"),
        livekit_url=os.environ["LIVEKIT_URL"],
    )


class TokenResponse(BaseModel):
    token: str
    livekit_url: str


@app.get("/token")
async def issue_token(room: str) -> TokenResponse:
    return TokenResponse(
        token=supervisor_token(room, identity=f"sup-{uuid.uuid4().hex[:6]}"),
        livekit_url=os.environ["LIVEKIT_URL"],
    )


class EndCallRequest(BaseModel):
    room: str


@app.post("/end-call", status_code=204)
async def end_call(req: EndCallRequest) -> None:
    """Force-end a call by deleting the LiveKit room.

    LiveKit disconnects every participant (agent + SIP) and sends BYE to the
    carrier, so this hangs up Twilio's leg too. 404 from LiveKit means the
    room already ended — treated as success (idempotent).
    """
    lkapi = api.LiveKitAPI()
    try:
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=req.room))
    except TwirpError as e:
        if e.code != "not_found":
            raise
    finally:
        await lkapi.aclose()
