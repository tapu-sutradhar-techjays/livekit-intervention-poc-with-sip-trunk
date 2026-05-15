# LiveKit Agents Spike — Findings & Production Plan

## Spike Outcome: GO

Three load-bearing patterns for SmartCaller v2 validated end-to-end.

| Pattern | Status |
| --- | --- |
| Outbound SIP telephony (Twilio trunk → LiveKit room) | Working (Secure Trunking disabled; re-enable for prod) |
| Stack-call agent swap mid-call (`BasicsAgent` → `CoverageAgent`) | Working; SIP leg stays continuous |
| Browser supervisor takeover (audio listen-in, mic toggle, end-call) | Working |

## Latency Findings

| Metric | Console (laptop, India) | Phone (with SIP/PSTN) | Production target |
| --- | ---: | ---: | ---: |
| e2e | ~2.0 s | ~2.2–2.5 s | **800–1500 ms** |
| Bottleneck | LLM TTFT ~1.5 s | same | — |

Pipeline is already fully streaming (Deepgram WS → OpenAI SSE → Cartesia WS) with preemptive LLM dispatch. No further streaming gains available.

## Deployment Decisions for v2

| Decision | Rationale |
| --- | --- |
| **LK Cloud Agents, single region `us-east`** | Region pinning via `lk agent create --region`. `us-east` co-locates with all three inference providers. Default LK routing optimizes for media locality (wrong for our LLM-bottlenecked workload), so one deliberate region beats multi-region. |
| **EU / India regions only for compliance-bound tenants** | GDPR / data residency overrides; `eu-central` and `ap-south` available at the cost of LLM TTFT. |
| **Routing decision lives in your API, not in LK** | Service reads tenant + destination + compliance flags, dispatches to the named regional agent. LK stays a dumb compute fabric. |
| **Tenant config travels in dispatch `metadata`** | Same agent codebase, branched at runtime by `tenant_id` / `prompt_id` / `voice_id` / patient list. No per-tenant deployments unless isolation is contractually required. |
| **FastAPI control plane hosted separately** | LK Cloud Agents only runs the worker. The orchestration HTTP layer is your service (Cloud Run / Fly / etc.). |

## Latency Optimization Stack

Apply in order; stop when the production target is met.

| Order | Lever | Expected gain | Effort | Cost |
| ---: | --- | ---: | --- | --- |
| 1 ✓ | Semantic turn detector (`livekit-plugins-turn-detector`) | 200–400 ms | done | none |
| 2 | LLM swap to Groq (Llama-3.1-8B-instant) | ~1000 ms | 10 min | Groq API key |
| 3 | Deploy worker to LK Cloud Agents `us-east` | additional 600–800 ms | half day | LK Agents pricing |
| 4 | OpenAI Realtime API (single-model STT+LLM+TTS) | takes e2e to ~500 ms | 1–2 weeks rewrite | only if 1+2+3 isn't enough |

Steps 1+2 alone project to bring phone e2e from ~2.4 s into ~900–1100 ms — clears the production target without a deployment change. Step 3 is about scale, ops, and tenant isolation — not latency.

## Risks to Track into v2

- **Twilio Secure Trunking** disabled for the spike; production needs TLS transport on the LiveKit trunk + matching termination URI on Twilio. Don't ship without it.
- **Default LK region routing** would send Indian rep calls to Mumbai (wrong region for LLM-bottlenecked workloads). If multi-region is ever deployed, force `us-east` via explicit dispatch.
- **Worker crash mid-call** leaves Twilio billing the carrier leg until LK room `empty_timeout` fires. Production needs proactive `delete_room` on worker shutdown.
- **LK Agents Issue #3841** (worker dying) not observed during this spike but stays on the watch-list.
