"""Force-end a call: deletes a LiveKit room, disconnects all participants
including the SIP leg (LiveKit sends BYE to the carrier).

Usage: uv run python scripts/end_call.py <room-name>
       uv run python scripts/end_call.py --all     # nuke every active room
"""
from __future__ import annotations
import asyncio
import sys
from dotenv import load_dotenv
from livekit import api

load_dotenv()


async def _delete(lkapi: api.LiveKitAPI, name: str) -> None:
    await lkapi.room.delete_room(api.DeleteRoomRequest(room=name))
    print(f"Deleted room: {name}")


async def main(args: list[str]) -> int:
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 1

    lkapi = api.LiveKitAPI()
    try:
        if args[0] == "--all":
            rooms = (await lkapi.room.list_rooms(api.ListRoomsRequest())).rooms
            if not rooms:
                print("No active rooms.")
                return 0
            for r in rooms:
                await _delete(lkapi, r.name)
            return 0
        for name in args:
            await _delete(lkapi, name)
        return 0
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
