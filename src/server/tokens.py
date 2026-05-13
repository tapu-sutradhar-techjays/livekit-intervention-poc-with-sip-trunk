"""JWT issuance for browser supervisors joining a call room."""
from __future__ import annotations
import os
from livekit import api


def supervisor_token(room: str, identity: str) -> str:
    """Issue a token allowing a supervisor to join `room`, publish (mic), and subscribe."""
    return (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name("Supervisor")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .to_jwt()
    )
