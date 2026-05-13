# LiveKit Agents PoC Spike

3-day validation spike for SmartCaller v2 framework choice. See `livekit-poc-spike-plan.md` for the full plan.

## Quick start

1. Copy `.env.example` to `.env` and fill in all values.
2. `uv sync`
3. `uv run python scripts/provision_sip_trunk.py` (one time)
4. Add returned `LIVEKIT_SIP_TRUNK_ID` to `.env`
5. Start worker in one terminal: `uv run python src/worker.py dev`
6. Place call in another: `uv run python scripts/place_call.py`
