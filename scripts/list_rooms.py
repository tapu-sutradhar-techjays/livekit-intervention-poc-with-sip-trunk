"""Print active LiveKit rooms + their participants. Useful for spotting leaks."""
from __future__ import annotations
import asyncio
import datetime as dt
from dotenv import load_dotenv
from livekit import api
from livekit.api.twirp_client import TwirpError

load_dotenv()


def _age(unix_seconds: int) -> str:
    if not unix_seconds:
        return "?"
    delta = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromtimestamp(unix_seconds, dt.timezone.utc)
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60}s"
    return f"{secs // 3600}h{(secs % 3600) // 60}m"


async def main() -> None:
    lkapi = api.LiveKitAPI()
    try:
        rooms = (await lkapi.room.list_rooms(api.ListRoomsRequest())).rooms
        if not rooms:
            print("No active rooms.")
            return
        for r in rooms:
            print(f"\nRoom: {r.name}  (sid={r.sid}, age={_age(r.creation_time)}, participants={r.num_participants})")
            try:
                parts = (await lkapi.room.list_participants(api.ListParticipantsRequest(room=r.name))).participants
            except TwirpError as e:
                if e.code == "not_found":
                    print("  (room ended between list and detail fetch)")
                    continue
                raise
            for p in parts:
                joined = _age(p.joined_at) if p.joined_at else "?"
                print(f"  - {p.identity:20s}  state={p.state}  joined={joined}  name={p.name!r}")
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
