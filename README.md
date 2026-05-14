# LiveKit Agents PoC Spike

3-day validation spike for SmartCaller v2 framework choice. See `livekit-poc-spike-plan.md` for the full plan.

## Quick start

1. Copy `.env.example` to `.env`. Fill in LiveKit Cloud + inference provider keys + `TEST_REP_PHONE_NUMBER`. The four `TWILIO_*` vars are only needed if you take the script path in step 3 below.
2. `uv sync --all-extras`
3. Register the outbound SIP trunk and put the returned ID into `.env` as `LIVEKIT_SIP_TRUNK_ID`. Pick one:
   - **LiveKit Cloud console (recommended)** — `SIP → Trunks → Create outbound`, point at your Twilio Elastic SIP Trunk URI + creds, copy the resulting trunk ID. Skip the four `TWILIO_*` env vars.
   - **Script path** — fill the four `TWILIO_*` vars in `.env`, then `uv run python scripts/provision_sip_trunk.py` (one time).
4. Start worker in one terminal: `uv run python -m src.worker dev`
5. Place call in another: `uv run python scripts/place_call.py`

## Supervisor UI (Day 3)

Same `.env` and worker. Add two terminals:

6. API server: `uv run uvicorn src.server.main:app --reload --port 8001`
7. Frontend: `cd frontend && npm install && npm run dev` — opens on http://localhost:5173, click **Place Call**.
