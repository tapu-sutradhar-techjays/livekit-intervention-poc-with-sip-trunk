# DEPLOYMENT — SmartCaller v2 on LiveKit Cloud Agents

Operational guide for taking this stack to production. Captures the deployment shape, region strategy, multi-tenant routing pattern, and the production-readiness checklist surfaced by the spike. For the GO rationale and measured latency, see [`DAY3-FINDINGS.md`](./DAY3-FINDINGS.md).

## Production Topology

```
                              Your control plane (Cloud Run / Fly / EC2)
                              ┌─────────────────────────────────────────┐
       Tenant request  ────→  │ POST /calls/start                       │
                              │   1. lookup tenant config (DB)          │
                              │   2. decide region (see decision tree)  │
                              │   3. create LK dispatch + SIP call      │
                              └────────────────┬────────────────────────┘
                                               │ LiveKit Server API
                                               ▼
                              ┌─────────────────────────────────────────┐
                              │           LiveKit Cloud                 │
                              │  ┌─────────────────────────────────┐    │
                              │  │  Agent fleet (us-east default)  │    │
                              │  │  • runs src/worker.py per call  │    │
                              │  │  • talks to Deepgram/LLM/TTS    │    │
                              │  └─────────────────────────────────┘    │
                              │  ┌─────────────────────────────────┐    │
                              │  │  SFU + SIP gateway              │    │
                              │  │  (your project's region)        │    │
                              │  └────────┬────────────────────────┘    │
                              └───────────┼─────────────────────────────┘
                                          │ SIP/RTP
                                          ▼
                                        Twilio (Elastic SIP Trunk, TLS)
                                          │
                                          ▼
                                        Carrier → rep's phone
```

Three planes, three different homes:

| Plane | Where it runs | What lives there |
| --- | --- | --- |
| **Control plane** | Your service (Cloud Run / Fly / Railway / EC2) | Tenant DB, prompt store, dispatch logic, auth, audit. *Not* LiveKit's job. |
| **Agent compute** | LiveKit Cloud Agents (`us-east` default) | `src/worker.py` and dependencies — STT/LLM/TTS clients run from here. |
| **Media + SIP** | LiveKit Cloud SFU + SIP gateway | Room hosting, WebRTC SFU, SIP trunk termination to Twilio. |

## Region Decision Tree

The control plane decides at call-initiation time which regional agent to dispatch. **Default to `us-east` for everyone**; only deviate for compliance.

```
tenant.data_residency == "EU"        → eu-central  (Frankfurt)
tenant.data_residency == "IN-only"   → ap-south    (Mumbai)
HIPAA tenant with US-only BAA        → us-east     (Ashburn)
otherwise                            → us-east     (default)
```

### Why default is `us-east` even for non-US reps

Counter-intuitive but measured: the LLM is the bottleneck, not the SIP↔SFU media RTT. `us-east` co-locates the worker with Deepgram + OpenAI + Cartesia, collapsing LLM TTFT from ~1500 ms to ~300 ms. The ~200 ms each-way media RTT cost to a remote SFU is smaller than the ~1200 ms LLM TTFT saving.

**Gotcha:** LiveKit's default region routing optimizes for "agent closest to user," which means an Indian rep would auto-route to `ap-south` if it's deployed. For this workload that's the wrong choice. Use **explicit dispatch** with the named regional agent, not auto-routing.

## Agent Deployment

Per [LiveKit's region docs](https://docs.livekit.io/deploy/admin/regions/agent-deployment/):

```bash
# Single-region (recommended default)
lk agent create --region us-east --config livekit.toml

# Multi-region (only if tenant compliance demands it)
lk agent create --region us-east    --config livekit.toml
lk agent create --region eu-central --config livekit.eu.toml
lk agent create --region ap-south   --config livekit.ap.toml
```

The same Python code (`src/worker.py`, `src/agents/*`) ships to every region. Differences live in:

- `livekit.toml` per region (env vars, possibly different inference provider keys per region for data residency).
- The **agent name** — use `agent_name = f"ibv-{region}"` (e.g. `ibv-us-east`, `ibv-eu-central`) so explicit dispatch can target a specific region without ambiguity. Avoids relying on LK's default region routing.

Region assignment is **immutable** post-creation; to change region you re-deploy a new agent and migrate dispatch.

## Multi-Tenant Configuration (no per-tenant deployments)

Don't fork the deployment per tenant. Pass tenant configuration in the dispatch `metadata` payload — the worker reads it on `JobContext` and constructs the appropriate agent at runtime.

Example envelope:

```json
{
  "call_id": "call_01H...",
  "tenant_id": "acme-health",
  "tenant": {
    "system_prompt_id": "ibv-v3",
    "voice_id": "cartesia-79a125e8-...",
    "llm_model": "groq/llama-3.1-8b-instant",
    "language": "en-US"
  },
  "call": {
    "type": "ibv",
    "patients": ["pat-A", "pat-B"],
    "rep_payer": "Aetna",
    "claim_id": "..."
  }
}
```

In `src/worker.py:entrypoint`, branch on `metadata["tenant"]`:

- Look up prompt body by `system_prompt_id` (from a cached store / Redis / S3 / config service).
- Pick the LLM, STT, TTS plugin by config values, not hardcoded constants.
- Pass tenant-specific args into `BasicsAgent(prompt=..., questions=...)`.

This is the spike's current path — already plumbs `patients` through metadata — extended to carry tenant identity and config refs.

**Per-tenant agent deployments** are an antipattern *unless* contractually required (isolated infra, dedicated quota). Even then, prefer separate LiveKit *projects* (full tenancy boundary) over forking the agent fleet.

## Production Readiness Checklist

Before shipping v2:

### Telephony
- [ ] **Re-enable Twilio Secure Trunking.** Set LiveKit outbound trunk `transport=SIP_TRANSPORT_TLS`; termination URI on Twilio must be the `:5061` endpoint with TLS. The spike disabled this for debugging — production must not.
- [ ] Verify Twilio account is **out of trial mode** and the target country is enabled in Voice Geo Permissions.
- [ ] Caller ID number on the trunk is owned and verified.
- [ ] Use the explicit dispatch path; do not rely on LK's default region routing.

### Worker lifecycle
- [ ] Implement `ctx.add_shutdown_callback` in the worker to `delete_room` on graceful shutdown — prevents orphan rooms (and orphan Twilio billing) when the worker exits cleanly.
- [ ] For ungraceful crashes, depend on LK's `empty_timeout` for cleanup. Tune `empty_timeout` per workload — default 5 min is too long for cost-sensitive deployments; consider 30–60 s.
- [ ] Monitor for [LK Agents Issue #3841](https://github.com/livekit/agents) (worker dying); pin `livekit-agents==1.5.8` until resolved.

### Latency
- [ ] Swap LLM provider to a fast/regional one (Groq Llama-3.1-8B-instant, Cerebras, or OpenAI Realtime). Reference: `src/worker.py:39` is the single-line change. See [`DAY3-FINDINGS.md`](./DAY3-FINDINGS.md) latency stack.
- [ ] Keep the semantic turn detector (`turn_detection=EnglishModel()`) enabled — already added at `src/worker.py:9`.
- [ ] Pre-`download-files` the turn-detector + Silero weights into the LK Agents deployment image (avoids cold-start downloads).

### Observability
- [ ] Wire `src/tracing.py` to your real OTLP destination (LangSmith / Honeycomb / Datadog). Tag every span with `tenant_id`, `region`, `call_id` — the metadata pipeline already carries these.
- [ ] Surface per-call cost (Twilio minutes + LLM tokens + STT/TTS seconds) to the tenant billing layer. The worker is the natural emit point.

### Auth & secrets
- [ ] Supervisor browser token endpoint (`/token`) currently has **no auth** (spike scope). Production must gate it — at minimum JWT-from-your-service, ideally short-lived per-call tokens scoped to a specific room.
- [ ] LiveKit API key/secret rotation policy. Don't ship the trunk's Twilio credentials in a shared `.env` — store in a secrets manager and inject per region.

### Browser supervisor (if shipping it)
- [ ] CORS in `src/server/main.py:17-22` is hardcoded to `localhost:5173`; replace with the production frontend origin allow-list.
- [ ] The browser audio attach (`TrackSubscribed` → `track.attach()`) and `room.startAudio()` unlock are already wired; reverify cross-browser (Safari + iOS Safari + Firefox).

## What This Repo Already Has

A lot of the v2 deployment surface is already prototyped — don't re-write what's working:

| Concern | Where it lives now |
| --- | --- |
| Outbound dial + agent dispatch | `src/server/main.py` (`/place-call`) |
| Force-end a call (and SIP leg) | `src/server/main.py` (`/end-call`), `scripts/end_call.py` |
| Per-call cleanup tooling | `scripts/list_rooms.py`, `scripts/end_call.py --all` |
| Per-call metadata plumbing | `src/worker.py:28-33` parses `ctx.job.metadata` |
| Agent handoff pattern | `src/agents/basics_agent.py` `next_segment` function_tool returning new Agent |
| Supervisor takeover RPC | `src/agents/takeover.py` + `frontend/src/takeover.ts` |
| Local dev without telephony | `python -m src.worker console` — useful for prompt iteration without burning carrier minutes |

The "ship to production" delta is roughly: tenant DB + dispatch routing logic + auth layer in front of `/place-call` + secrets per region + observability tags. The agent-side code is largely production-ready.

## Latency Targets (Recap)

| e2e on the phone | Feel |
| ---: | --- |
| < 800 ms | Native cadence |
| 800–1500 ms | **Production target for IBV** |
| 1500–2500 ms | Noticeably "the AI" |
| > 2500 ms | Unusable for back-and-forth |

Spike measured ~2.2–2.5 s; latency stack (Groq swap + `us-east` deploy) projects ~900–1100 ms.

## References

- [`DAY3-FINDINGS.md`](./DAY3-FINDINGS.md) — spike GO/NO-GO writeup with measured numbers and risks.
- [LiveKit region deployment docs](https://docs.livekit.io/deploy/admin/regions/agent-deployment/) — `lk agent create --region` mechanics, available regions.
- [`livekit-poc-spike-plan.md`](../livekit-poc-spike-plan.md) — the original 3-day spike plan.
