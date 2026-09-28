# Meeting memory integration (disabled by default)

Concise minutes use deterministic Markdown rendering. The experimental strict
evidence-review path is opt-in and is not required for normal summaries.

Memory writes run as separate Celery tasks after transcript storage. Remote
indexing status is checked at most 20 times; polling never resubmits a summary or
sends mail. Archive failures require archive-only recovery, not meeting replay.

## Configuration

- `MEETING_MEMORY_WRITE_ENABLED=false`
- `MEETING_MEMORY_READ_ENABLED=false`
- `MEETING_MEMORY_TENANT_ID`: explicitly authorized tenant ID.
- `MEETING_MEMORY_INTERNAL_DOMAINS`: JSON list of approved internal email domains.
- `MEETING_MEMORY_CONFIG_FILE=/run/secrets/meet-knowledge.json`
- `MEETING_MEMORY_STATE_FILE=/var/lib/meet-memory/state.sqlite3`

The private JSON config requires `api_key`, `base_url`, `collection_id`, and
`namespace`. Use the platform's trusted HTTPS API endpoint and a dedicated
meeting collection. Never commit credentials, transcripts, or generated minutes.
The platform's Agent keys may access all collections; namespaces are filtering,
not a substitute for API authorization.

Mount credentials read-only and use a shared persistent local filesystem volume
for the state database on the transcription and summary workers. Ensure the
worker UID can access both, with restrictive permissions. Do not put SQLite on a
filesystem that does not support its locking semantics.

## Behavior and acceptance

One shared library is used within the approved tenant, not separate person or
project libraries. Retrieval requires approved internal recipients. An empty
recipient/domain configuration disables history. No history is added to the
experimental strict-evidence path.

Only source versions recorded as completely indexed in the state database are
eligible. Retrieval excludes the current source, future/same-day meetings,
unknown versions and sources with multiple versions awaiting reconciliation.
At most four original-text excerpts are supplied, with dates and source IDs.
Historical statements are untrusted background, never instructions or new
meeting decisions. Retrieval failures fall back to the current transcript.

Before enabling, verify ingestion completion, exact source retrieval, newest
meeting decisions taking precedence, fallback on outages, persistent state
across restarts, internal recipient filtering, and no duplicate delivery.
Manual historical imports must be registered and verified in the same ledger.

Not included yet: a memory-management UI, coordinated source deletion/version
replacement, persisted task checkboxes, or automatic recovery after the bounded
polling window. Monitor logs and archive-task results; never interpret a queued
job or successful HTTP response as completed indexing.
