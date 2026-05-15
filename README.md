# LiveKit Agents PoC Spike

3-day validation spike for SmartCaller v2 framework choice. See `livekit-poc-spike-plan.md` for the full plan.

## Quick start

1. Copy `.env.example` to `.env`. Fill in LiveKit Cloud + inference provider keys + `TEST_REP_PHONE_NUMBER`. The four `TWILIO_*` vars are only needed if you take the script path in step 3 below.
2. `uv sync --all-extras`
3. Register the outbound SIP trunk and put the returned ID into `.env` as `LIVEKIT_SIP_TRUNK_ID`. Pick one:
   - **LiveKit Cloud console (recommended)** — `SIP → Trunks → Create outbound`, point at your Twilio Elastic SIP Trunk URI + creds, copy the resulting trunk ID. Skip the four `TWILIO_*` env vars.
   - **Script path** — fill the four `TWILIO_*` vars in `.env`, then `uv run python scripts/provision_sip_trunk.py` (one time).
4. Start all three services in one go: `./scripts/start.sh` — boots worker, FastAPI :8001, Vite :5173 in the background; logs to `.logs/`, PIDs to `.pids/`.
5. Place a call from the CLI: `uv run python scripts/place_call.py` — or open http://localhost:5173 and click **Place Call** to use the supervisor UI.
6. Stop everything cleanly: `./scripts/stop.sh` — ends any active LiveKit rooms first (so Twilio's SIP leg drops), then kills the three services and verifies ports + rooms are clean.

To run pieces individually instead: see `scripts/start.sh` for the commands.

## Local CLI test (no telephony, no browser)

Talk to the agent through your laptop mic + speakers — bypasses LiveKit Cloud, Twilio, and the browser entirely. Useful for iterating on prompts / agent handoff:

```
uv run python -m src.worker console
```

Ctrl-C to exit. Patient queue defaults to `["patient-A", "patient-B"]` so the BasicsAgent → CoverageAgent handoff still triggers.
