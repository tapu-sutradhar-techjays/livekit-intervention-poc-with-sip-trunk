# AUDIO-RECORDING — Per-Call Recording to a Tenant-Owned GCS Bucket

How to capture room audio on LiveKit and land it in a per-tenant private Google Cloud Storage bucket, with the HIPAA controls the recording pipeline needs around it. Companion to [`DEPLOYMENT.md`](./DEPLOYMENT.md).

## TL;DR

LiveKit ships this natively via **Egress**. The Egress service subscribes to the room, mixes/encodes the audio, and streams the upload directly to GCS — no intermediate storage, no extra service to run. Trigger it from the worker entrypoint; LiveKit finalizes the upload when the room ends and fires a webhook so your control plane can record the artifact.

The compliance lift is **not** in the LiveKit wiring (it's ~20 lines). It's in the BAA paperwork with LiveKit + Google, and the bucket-side controls (CMEK, audit logs, retention, scoped IAM).

## Egress Flavors

| Flavor | What you get | When to use |
| --- | --- | --- |
| `RoomCompositeEgress` with `audio_only=true` | **One mixed `.ogg`/`.mp3`** — agent + rep mixed together | Default for IBV. Cheapest, one file per call, simplest pipeline. |
| `TrackEgress` | Separate file per published track (one per participant) | When downstream needs diarization / per-speaker QA scoring without a separate diarizer. Started once per track. |
| `ParticipantEgress` | One file per participant, all their tracks composited | Multi-track participants (rare for IBV). |

Audio-only egress is billed at a lower rate than video egress.

## Worker-Side Wiring

Trigger inside `src/worker.py:entrypoint` right after `ctx.connect()`. The egress runs in parallel with the agent and finalizes on room close.

```python
# src/worker.py
from livekit import api
import os

async def entrypoint(ctx: JobContext):
    await ctx.connect()

    # tenant_id + recording config come from ctx.job.metadata
    # (see DEPLOYMENT.md "Multi-Tenant Configuration")
    egress_req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        audio_only=True,
        file_outputs=[api.EncodedFileOutput(
            file_type=api.EncodedFileType.OGG,
            filepath=f"calls/{tenant_id}/{ctx.room.name}.ogg",
            gcp=api.GCPUpload(
                bucket=tenant_cfg["recording"]["gcs_bucket"],
                credentials=tenant_cfg["recording"]["gcs_sa_json"],  # full SA JSON string
            ),
        )],
    )

    lkapi = api.LiveKitAPI()
    egress_info = await lkapi.egress.start_room_composite_egress(egress_req)
    await lkapi.aclose()
    # ... rest of agent setup
```

**Stop semantics:**
- Auto-stops when the room ends (your `delete_room` shutdown callback in the DEPLOYMENT.md checklist will trigger it).
- For explicit control: `await lkapi.egress.stop_egress(egress_id=egress_info.egress_id)` from a shutdown callback. Belt-and-braces if you've ever seen orphan egresses.

**Path convention:** `calls/{tenant_id}/{room_name}.ogg` — keeps tenant isolation visible in object paths and matches the call_id you already plumb through metadata.

## Recording State Tracking

The naive wiring above starts egress at `entrypoint`. That's fine until you realise outbound IBV calls have a meaningful no-answer / voicemail rate, and you don't want either (a) blank recordings in your HIPAA bucket or (b) recorded voicemail audio sitting there until somebody prunes it. The fix is to gate the egress start on "rep audio actually arrived" — but then "no recording in bucket" becomes ambiguous (no-answer? voicemail? bug? Egress failure?), which is not OK for HIPAA. An auditor asking *"where is the recording for call X?"* needs a defensible answer for every call.

**Solution: make "why is there no recording" a queryable state**, written by the worker and the egress webhook, never inferred from absence.

### `call_recordings` table

One row per call, written at dispatch in `status='pending'`, mutated through its lifecycle:

```
call_recordings
─────────────────
call_id              (FK to calls — also serves as room_name)
tenant_id
status               enum (see below)
status_reason        text     -- e.g. "voicemail_detected", "sip_487_no_answer"
egress_id            nullable -- LK's egress ID, from start_room_composite_egress
expected_gcs_uri     not null -- written at dispatch from the path convention
actual_gcs_uri       nullable -- written by webhook handler on EGRESS_COMPLETE
gcs_object_name      nullable -- bucket-relative object key, for signed URL generation
duration_ms          nullable
bytes                nullable
content_sha256       nullable -- from GCS CRC32C/MD5 on finalize, for tamper detection
recording_started_at nullable
recording_ended_at   nullable
updated_at
```

### Status enum

| Status | Set by | Means |
| --- | --- | --- |
| `pending` | Control plane on dispatch | Call placed, waiting to see if rep answers |
| `recording` | Worker, when `start_room_composite_egress` succeeds | Egress is running; `egress_id` populated |
| `completed` | Webhook handler on `egress_ended` (success) | File is in GCS; `gcs_uri` + hash populated |
| `skipped_no_answer` | Worker shutdown callback | SIP leg ended before rep audio ever fired (busy / no-answer / declined) |
| `skipped_voicemail` | Worker, after AMD or first-turn classifier | We deliberately did not record |
| `failed_to_start` | Worker, in start_egress try/except | LK Egress API rejected the request |
| `failed_in_flight` | Webhook handler on `egress_ended` (failure) | Egress started but did not finalize cleanly |
| `orphaned` | Janitor (see below) | Row stuck in `pending`/`recording` past the SLA |

Forensic query is now trivial:

```sql
SELECT call_id, status, status_reason, recording_ended_at
FROM call_recordings WHERE call_id = $1;
```

Every call has a row; every row has a reason.

### Linking strategy — making sure the row gets the GCS URI

Webhook delivery is not guaranteed. A single dropped `egress_ended` event would leave a row stuck in `recording` with no `gcs_uri` — unacceptable for HIPAA where you need to answer "where is the artifact for call X?" deterministically. Solution: **three-way bookkeeping**, so any one of three writers can populate the URI.

| When | Writer | What it writes | Why it matters |
| --- | --- | --- | --- |
| Dispatch | Control plane | `expected_gcs_uri` (computed from path convention) | URI is on the row before recording even starts; survives all downstream failures |
| Egress start | Worker | `egress_id` returned by `start_room_composite_egress` | Lets the janitor query `ListEgress` and recover the URI if the webhook never arrives |
| Webhook | Webhook handler | `actual_gcs_uri`, `bytes`, `duration_ms`, `content_sha256` | Authoritative — confirms upload finalized; mismatch with `expected_gcs_uri` is a paging signal |

**Make `room_name = call_id` at dispatch.** Removes the need for any room_name → call_id lookup table — the webhook's `room_name` field *is* the call_id. (`call_id` should be opaque/UUID-ish, not a guessable sequence, since it appears in the GCS path and signed URLs.)

Deterministic path convention (same on both sides):

```python
# control plane (at dispatch) AND worker (in start_recording) compute the SAME thing:
def expected_gcs_uri(tenant_cfg, call_id):
    return f"gs://{tenant_cfg['recording']['gcs_bucket']}/calls/{tenant_cfg['tenant_id']}/{call_id}.ogg"
```

If `actual_gcs_uri != expected_gcs_uri` after the webhook fires, something drifted between dispatch and worker — page someone.

### Worker-side: conditional start + shutdown reason

Extend the worker from the previous section to (a) gate on `track_subscribed` for the rep, and (b) record the reason in the shutdown callback if egress never started:

```python
from livekit import rtc

async def entrypoint(ctx: JobContext):
    await ctx.connect()
    state = {"started": False, "voicemail": False}

    @ctx.room.on("track_subscribed")
    def on_track(track, pub, participant: rtc.RemoteParticipant):
        if state["started"] or state["voicemail"]:
            return
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if not participant.identity.startswith("sip_"):  # adjust to your SIP identity scheme
            return
        state["started"] = True
        asyncio.create_task(_start_and_mark_recording(ctx, call_id))

    async def on_shutdown():
        if state["started"]:
            return  # webhook handler will close out the row
        if state["voicemail"]:
            await control_plane.mark_recording(
                call_id, status="skipped_voicemail", reason="amd_or_classifier")
        else:
            await control_plane.mark_recording(
                call_id, status="skipped_no_answer", reason="no_sip_audio_track")
    ctx.add_shutdown_callback(on_shutdown)
```

`_start_and_mark_recording` calls `start_room_composite_egress`, then PATCHes the row to `status='recording'` with the returned `egress_id`. Wrap that call in try/except → `failed_to_start` on exception.

### Webhook handler — closing the row

LiveKit fires `egress_ended` when the upload finalizes. Handler:

```python
@app.post("/webhooks/livekit/egress")
async def on_egress(event: EgressWebhook):
    verify_lk_signature(event)
    info = event.egress_info
    call_id = info.room_name  # because room_name = call_id at dispatch

    if info.status == EgressStatus.EGRESS_COMPLETE:
        result = info.file_results[0]
        gcs_meta = gcs.stat(result.location)  # fetches CRC32C / MD5 / size from GCS
        await control_plane.mark_recording(
            call_id,
            status="completed",
            actual_gcs_uri=result.location,         # e.g. "gs://acme-health-recordings-us/calls/acme-health/call_01H.../...ogg"
            gcs_object_name=result.filename,       # the object key, useful for signed URL generation
            duration_ms=result.duration,
            bytes=gcs_meta.size,
            content_sha256=gcs_meta.crc32c_or_md5,
            recording_ended_at=info.ended_at,
        )
        # mismatch with expected URI = drift between dispatch and worker — page
        await alert_if_uri_mismatch(call_id, result.location)
    else:
        await control_plane.mark_recording(
            call_id, status="failed_in_flight", reason=info.error)
```

### Janitor — reconciling stuck rows

A row stuck in `pending` (call dispatched, worker never reached `track_subscribed` *or* never wrote shutdown reason — usually a worker crash) or `recording` (egress started but webhook never arrived — usually a webhook delivery failure) for longer than expected is a signal. Run a periodic job:

```sql
-- stuck pending (worker likely crashed without shutdown callback)
SELECT call_id FROM call_recordings
WHERE status = 'pending' AND updated_at < now() - interval '1 hour';

-- stuck recording (webhook never delivered)
SELECT call_id, egress_id FROM call_recordings
WHERE status = 'recording' AND updated_at < now() - interval '1 hour';
```

For each, query LK's `ListEgress` by `egress_id` (or by `room_name`), reconcile to terminal state, mark `orphaned` if LK has no record. **Page on non-zero orphan rate** — it's a quiet failure mode that otherwise stays invisible until an auditor asks.

### Pattern trade-off (for the record)

The "always start, prune blanks" alternative is operationally simpler but has a HIPAA cost — voicemail/ringback audio briefly lands in the bucket. Captured here so the trade-off is explicit, not because it's the recommendation:

| | Conditional start (above) | Always start, prune blanks |
| --- | --- | --- |
| Egress cost on no-answer calls | $0 | ~½¢ each |
| Voicemail PHI in bucket | Never | Briefly, until janitor deletes |
| Code complexity | Higher | Lower |
| Forensic ambiguity | Zero (status+reason on every call) | Zero (duration gate on every call) |

For HIPAA-sensitive IBV, use the conditional pattern.

## Per-Tenant Bucket Pattern

For the multi-tenant deployment shape in `DEPLOYMENT.md`, the clean topology is:

```
Tenant config (control plane DB)
  ├─ recording.gcs_bucket            → "acme-health-recordings-us"
  └─ recording.gcs_credentials_ref   → secrets-manager path (NOT the JSON itself)

Control plane (POST /calls/start)
  1. Looks up tenant config
  2. Fetches SA JSON from secrets manager
  3. Either:
     a. Passes through dispatch metadata (simple, but JSON visible to LK)
     b. Passes only call_id + tenant_id; worker callbacks to fetch SA (HIPAA-correct)
```

**Don't put SA JSON in `room.metadata`.** Room metadata is visible to participants (and to the SFU). For HIPAA, the worker should make an authenticated callback to your control plane with `call_id` to retrieve the upload credentials — secrets stay in your secrets manager, never on the wire to LiveKit beyond the single egress request.

One bucket + one service account **per tenant** keeps the blast radius of a leaked SA to that tenant only. Don't share buckets across tenants.

## HIPAA Posture

The recording pipeline touches PHI (recorded voice, potentially member IDs, DOB, claim numbers spoken on-call). Each hop needs the right paperwork and controls:

### 1. LiveKit Cloud — needs a BAA

- Confirm with LiveKit sales which tier signs a BAA (typically Scale / Enterprise).
- Self-hosted LiveKit sidesteps the BAA question since media never leaves your VPC — but you take on the operational burden of running SFU + Egress + SIP gateway.
- Without a BAA, you cannot legally send PHI through LiveKit Cloud, full stop.

### 2. E2EE vs. Egress — pick one

LiveKit offers client-side E2EE for the media path. **Egress cannot record an E2EE room** — it has to see plaintext frames to mix and encode. For HIPAA the standard posture is:

> BAA with LiveKit + SRTP-in-transit + encrypted-at-rest in your bucket = compliant.
> E2EE is a stronger guarantee but mutually exclusive with server-side recording.

If a tenant contractually requires E2EE, the only path is client-side recording (browser/native SDK writes the file) and that's not what this stack does.

### 3. Google Cloud — needs a BAA + bucket controls

| Control | Why | How |
| --- | --- | --- |
| **BAA with Google Cloud** | Required for any PHI in GCS | Sign via GCP console (Account settings → Legal) |
| **HIPAA-eligible region** | BAA only covers eligible services in eligible regions | `us-central1`, `us-east1`, etc. — check current GCP HIPAA-eligible service list |
| **CMEK (customer-managed KMS key)** | HIPAA prefers customer-controlled keys, lets you revoke access by destroying the key | `gcloud storage buckets update gs://bucket --default-kms-key=projects/.../keyRings/.../cryptoKeys/...` |
| **Uniform bucket-level access** | Disables per-object ACLs — IAM is the only access path, auditable | `--uniform-bucket-level-access` on bucket create |
| **Public access prevention = enforced** | Hard guarantee the bucket cannot be made public, even by accident | `--public-access-prevention=enforced` |
| **Cloud Audit Logs — Data Access** | HIPAA requires access tracking, not just admin actions | Enable Data Access logs for `storage.googleapis.com` in the project's audit config |
| **Object retention lock + lifecycle** | HIPAA retention is typically 6 years | Bucket-level retention policy + locked retention if regulator requires WORM |
| **Scoped service account** | Egress only needs to write, not read or delete | `roles/storage.objectCreator` on that one bucket — NOT `objectAdmin`, NOT project-wide |
| **VPC Service Controls** (optional, stronger) | Prevents data exfil from the bucket to outside your VPC perimeter | Service perimeter around the project; egress IPs allowed in |

### 4. Consent / Recording Disclosure

US outbound calls for IBV typically require a recording disclosure at the top of the call. That's a script issue, not a LiveKit issue — bake it into the system prompt and verify the first agent utterance. State-by-state two-party-consent laws vary; check the legal matrix per tenant.

### 5. Webhook → Audit Trail

LiveKit fires the `egress_ended` webhook when the upload finalizes. Wire your control plane to:

1. Receive the webhook (HMAC-verify the LK signature).
2. Insert a row in your `call_recordings` table: `call_id`, `tenant_id`, `gcs_uri`, `duration_ms`, `bytes`, `egress_id`, `finalized_at`.
3. Optionally fetch the object's CRC32C/MD5 from GCS and store it — gives you a content hash for tamper detection.

That row is the audit trail tying a call to its artifact. Without it, an auditor cannot answer "which recording belongs to call_id X?"

## Bucket Bootstrap (gcloud)

Per-tenant bucket setup, run once per onboarding:

```bash
TENANT=acme-health
PROJECT=your-hipaa-project
REGION=us-central1
BUCKET="${TENANT}-recordings-${REGION}"
KMS_KEY="projects/${PROJECT}/locations/${REGION}/keyRings/recordings/cryptoKeys/${TENANT}"
SA_NAME="lk-egress-${TENANT}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

# 1. KMS key (one per tenant — enables per-tenant key revocation)
gcloud kms keyrings create recordings --location=$REGION --project=$PROJECT 2>/dev/null || true
gcloud kms keys create $TENANT \
  --location=$REGION --keyring=recordings --purpose=encryption --project=$PROJECT

# 2. Bucket with uniform access, public access prevention, CMEK, retention
gcloud storage buckets create gs://$BUCKET \
  --project=$PROJECT \
  --location=$REGION \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --default-storage-class=STANDARD \
  --default-encryption-key=$KMS_KEY

gcloud storage buckets update gs://$BUCKET \
  --retention-period=6y \
  --versioning

# 3. Service account scoped to write-only on this one bucket
gcloud iam service-accounts create $SA_NAME --project=$PROJECT
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectCreator"

# Allow the SA to use the CMEK key
gcloud kms keys add-iam-policy-binding $TENANT \
  --location=$REGION --keyring=recordings --project=$PROJECT \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudkms.cryptoKeyEncrypterDecrypter"

# 4. Key for the SA → stash in your secrets manager, NOT in git
gcloud iam service-accounts keys create /tmp/${SA_NAME}.json \
  --iam-account=$SA_EMAIL

# 5. Audit logging — enable Data Access logs for storage in the project's IAM policy
#    (one-time per project, see GCP docs for the audit config JSON)
```

After this, `/tmp/${SA_NAME}.json` goes into your secrets manager (Vault / GCP Secret Manager / AWS Secrets Manager) under `tenants/${TENANT}/recording/gcs_sa_json`. The control plane reads it at dispatch time.

## Serving Recordings to the Frontend

Storing the recording is half the problem. Playing it back to an authorized user — without breaking HIPAA — is the other half. The bucket is locked down (`public-access-prevention=enforced`, IAM-only), so the browser cannot fetch a `gs://` URI directly. **You must mint short-lived V4 signed URLs server-side**, after authentication, authorization, and an audit log write.

### What NOT to do

- **Don't make the bucket public**, even "just for testing." Once a HIPAA bucket is briefly public, you have a disclosable incident.
- **Don't expose `gs://` URIs to the browser** — they're internal references, not user-facing URLs.
- **Don't put the service-account JSON in the frontend**, in env files served to the browser, or in localStorage. Ever.
- **Don't issue long-lived (>1 hour) signed URLs.** If one leaks via logs/screenshots/Slack, the exposure window matters.
- **Don't reuse the same signed URL across requests.** Generate fresh every time; never cache them server-side.

### The flow

```
Browser (session cookie)
  → GET /api/calls/{call_id}/recording
    → API: authenticate user (session)
    → API: authorize (user.tenant_id == call.tenant_id, user has 'view_recording' role)
    → API: look up call_recordings row by call_id
    → API: write recording_access_log row (BEFORE returning URL — log even on denial)
    → API: V4 sign gs://bucket/object with TTL 15–30 min using the per-tenant SA
    → API: return { url, expires_at, duration_ms }
  → Browser: <audio src={url} controls />
    → GCS serves the file directly with HTTP Range support (scrubbing works natively)
```

### Backend: signed URL endpoint

```python
from datetime import timedelta
from google.cloud import storage
from google.oauth2 import service_account

@app.get("/api/calls/{call_id}/recording")
async def get_recording_url(call_id: str, user: User = Depends(current_user)):
    row = await db.fetch_call_recording(call_id)
    if not row:
        await audit.log(user, call_id, action="play", result="not_found")
        raise HTTPException(404)

    # Tenant isolation — never trust the call_id alone; cross-check against user's tenant
    if row.tenant_id != user.tenant_id:
        await audit.log(user, call_id, action="play", result="tenant_mismatch")
        raise HTTPException(403)

    if not user.has_permission("view_recording", tenant=row.tenant_id):
        await audit.log(user, call_id, action="play", result="rbac_denied")
        raise HTTPException(403)

    if row.status != "completed":
        await audit.log(user, call_id, action="play", result=f"not_ready:{row.status}")
        raise HTTPException(409, detail=f"Recording not available: {row.status}")

    # Per-tenant SA — same one that wrote the object, scoped objectCreator+objectViewer
    sa_creds = await secrets.get_tenant_sa(row.tenant_id)
    creds = service_account.Credentials.from_service_account_info(sa_creds)
    client = storage.Client(credentials=creds, project=creds.project_id)
    blob = client.bucket(row.bucket_name).blob(row.gcs_object_name)

    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=30),
        method="GET",
        response_disposition=f'inline; filename="call-{call_id}.ogg"',
    )

    await audit.log(
        user, call_id,
        action="play",
        result="url_issued",
        gcs_uri=row.actual_gcs_uri,
        signed_url_ttl_min=30,
    )
    return {
        "url": url,
        "expires_at": now() + timedelta(minutes=30),
        "duration_ms": row.duration_ms,
    }
```

**Note on credentials:** the per-tenant SA needs `roles/storage.objectViewer` on the bucket (in addition to `objectCreator` for writes). For tighter separation, use two SAs per tenant — one for Egress writes, one for signed URL reads — so a compromise of the read key doesn't grant write access and vice versa.

### Frontend: playback

```typescript
async function getRecordingUrl(callId: string): Promise<string> {
  const res = await fetch(`/api/calls/${callId}/recording`, {
    credentials: 'include',
    headers: { 'Cache-Control': 'no-store' },
  });
  if (!res.ok) throw new Error(`Recording unavailable: ${res.status}`);
  const { url } = await res.json();
  return url;
}

// In the component
const [url, setUrl] = useState<string>();
useEffect(() => { getRecordingUrl(callId).then(setUrl); }, [callId]);
return url ? <audio src={url} controls preload="metadata" /> : <Spinner />;
```

The `<audio>` element issues HTTP Range requests to GCS automatically — scrubbing, seek, partial buffering all work without extra code.

### Response hardening

On the `/recording` endpoint:

```
Cache-Control: no-store, no-cache, must-revalidate, private
Pragma: no-cache
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
```

`Cache-Control: no-store` keeps the signed URL out of browser caches and any CDN/proxy in front of your API. `Referrer-Policy: no-referrer` prevents the URL leaking via outbound requests on the page (analytics pixels, third-party widgets).

For high-sensitivity playback, consider rendering the `<audio>` inside an iframe with `sandbox="allow-same-origin"` to isolate it from any other JS on the page.

### Audit log table

HIPAA requires you to be able to answer *"who has listened to call X, when, and from where."* That data needs to live in your DB, not just in Cloud Audit Logs (those show *the signed URL request* hitting GCS, but not which application-user is behind it).

```
recording_access_log
─────────────────────
id
user_id
tenant_id
call_id
action               -- 'play' | 'download' | 'list'
result               -- 'url_issued' | 'rbac_denied' | 'tenant_mismatch' | 'not_found' | 'not_ready:...'
gcs_uri              nullable
signed_url_ttl_min   nullable
ip_address
user_agent
created_at
```

**Log denied requests too.** A pattern of `rbac_denied` from one user is a security signal you want to see, and "we logged that you weren't allowed in" is exactly the audit story HIPAA wants.

### TTL: how long should signed URLs live?

| TTL | Use case | Trade-off |
| --- | --- | --- |
| 5 min | High-sensitivity (legal review of a specific recording) | User must hit play immediately; if they pause mid-load and come back, URL is dead |
| **15–30 min** | **Default for typical playback UIs** | Long enough to listen to a full IBV call (~5–10 min) without refresh; short enough that leaks are bounded |
| 60 min | Long-form recordings, multi-call reviews | Wider exposure window; only do this if the recordings are routinely >30 min |

For IBV (5–10 min calls), **30 min is the sweet spot**. If a user lets the page sit overnight, the URL is dead and the next play triggers a fresh authorized request — which is what you want.

### When to proxy instead of signing

Signed URLs are right for ~95% of cases. Switch to **streaming through your backend** (your API reads from GCS, pipes to the client) when:

- You need per-byte access control (kill the stream mid-playback if the session is revoked).
- You need watermarking — inject a user-specific signal so a leaked recording is traceable.
- Your enterprise customer's network policy bans direct GCS access from end-user devices.

Costs: your backend pays egress bandwidth twice (GCS→backend, backend→user) and you carry the streaming connection. For typical IBV review UIs, this is overkill. Signed URL + good audit logging is the right balance.

### One more lever — VPC Service Controls

If you want to *guarantee* that signed URLs can only be used from within your VPC perimeter (defense-in-depth against a URL leaking outside the org), put the bucket inside a VPC-SC perimeter and have your backend proxy the bytes. Signed URLs handed to external browsers won't work from outside the perimeter. This is enterprise-tier paranoia — not necessary for most HIPAA workloads but worth knowing exists.

## What's NOT in scope for this doc

- **Live transcription egress** — separate Egress flavor (`StartTrackEgress` with a websocket URL) that streams audio to your STT for live captions or call monitoring. Different use case from "store the artifact."
- **PII redaction in the recording** — if you need to scrub spoken member IDs/DOBs before storage, that's a post-egress processing pipeline (download → diarize → ASR → redact spans → re-encode). Not something LiveKit does inline.
- **Real-time call monitoring by supervisor** — the supervisor takeover path (`src/agents/takeover.py`) already covers live monitoring without needing the recording.

## Implementation Checklist

Before enabling in production:

- [ ] LiveKit BAA signed (LiveKit Cloud Scale/Enterprise).
- [ ] Google Cloud BAA signed.
- [ ] Per-tenant bucket bootstrapped (script above) in a HIPAA-eligible region.
- [ ] CMEK key per tenant; SA scoped to `objectCreator` on the single bucket.
- [ ] SA JSON in secrets manager; control plane fetches at dispatch.
- [ ] Worker reads recording config via callback (not via room metadata).
- [ ] `call_recordings` table created with the status enum above.
- [ ] Control plane writes `pending` row at dispatch.
- [ ] Worker gates egress on `track_subscribed` for the SIP participant.
- [ ] Worker shutdown callback writes `skipped_no_answer` / `skipped_voicemail` when egress never started.
- [ ] `egress_ended` webhook handler closes the row to `completed` / `failed_in_flight`.
- [ ] Janitor reconciles stuck `pending` / `recording` rows; pages on non-zero orphan rate.
- [ ] `room_name = call_id` at dispatch; control plane writes `expected_gcs_uri` on the pending row.
- [ ] Webhook handler writes `actual_gcs_uri` + `bytes` + `content_sha256`; alerts on expected/actual mismatch.
- [ ] Per-tenant SA has `objectViewer` (or a second read-only SA) for signed URL generation.
- [ ] `/api/calls/:id/recording` endpoint: authn → tenant check → RBAC → audit-log → V4 signed URL (30 min TTL).
- [ ] `recording_access_log` table created; denied attempts logged too.
- [ ] Response hardening on the URL endpoint: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`.
- [ ] Recording disclosure in agent's opening utterance, per state.
- [ ] Retention lifecycle policy on bucket matches contractual SLA.
- [ ] Cloud Audit Logs (Data Access) enabled for `storage.googleapis.com` in the project.
- [ ] Shutdown callback in worker calls `stop_egress` defensively (orphan protection).
- [ ] Cost monitoring: egress minutes show up on the LK invoice — surface to tenant billing alongside Twilio + LLM cost.

## References

- [LiveKit Egress overview](https://docs.livekit.io/home/egress/overview)
- [LiveKit GCP upload config](https://docs.livekit.io/transport/media/ingress-egress/egress/outputs)
- [LiveKit auto-egress on room create](https://docs.livekit.io/transport/media/ingress-egress/egress/autoegress)
- [GCP HIPAA implementation guide](https://cloud.google.com/security/compliance/hipaa)
- [`DEPLOYMENT.md`](./DEPLOYMENT.md) — multi-tenant dispatch + region strategy this builds on.
