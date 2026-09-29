# Person-indexed shared meeting memory (not deployed)

This is an optional layer on top of the existing shared vector library, not a
private knowledge library per user. It stores identity mappings, tasks, enduring
responsibilities, and append-only evidence in additive `pm_*` SQLite tables.
Vector documents and the existing `archive` table are not rewritten.

## Processing

1. Transcription passes participant account IDs/names to the summary job.
2. Before generating minutes, resolve participants and read bounded personal
   cards alongside the existing retrieved historical excerpts. Exact accounts
   match automatically; names/aliases only match if unambiguous. Different
   accounts with identical names are not merged automatically. No email-domain
   filter is applied; tenant isolation remains mandatory.
3. After normal delivery succeeds, enqueue a separate personal-memory extraction
   task. It uses the original transcript, not the generated summary. Failure never
   retries meeting delivery. Source IDs plus content digests prevent replay; changed
   versions require reconciliation rather than silently duplicating memories.
4. Extracted quotes must be complete timestamped lines present in this meeting.
   Unknown/ambiguous ownership stays unassigned and needs confirmation. Completion
   requires an affirmative completion statement, not silence, a question, or a
   future plan. A one-off task does not establish a permanent responsibility.
5. Only earlier meeting timestamps enter the generation context. Same-day meetings
   work when full timestamps are available; date-only input is conservatively
   treated as end-of-day. Each attendee gets up to eight prioritized records,
   within an 18,000-character shared budget. Historical content is untrusted and
   cannot override this meeting. Unmentioned tasks remain unchanged; inherited
   deadlines retain their original meeting date/source.

## Confirmation and correction

`/memory-admin` is an administrative HTML page with no embedded credentials or
meeting data. Its requests use the existing tenant bearer credential. It supports
viewing people, current responsibilities/tasks and source quotes, correcting
owners/text/deadlines/status, explicit completion, and viewing change history.
Aliases can be corrected; two profiles can be explicitly merged, preserving item
history. Concurrent stale edits return HTTP 409. Human corrections take precedence;
subsequent conflicting model proposals are separate review candidates.

Data endpoints under `/api/v2/personal-memory` are authenticated and enforce the
configured tenant. The page holds a credential only in page memory, never browser
storage. This is an **administrator-only** first version: do not distribute the
service's privileged tenant credential to ordinary meeting participants. Serve it
only through an authenticated admin/internal route over HTTPS. The normal Meet
frontend currently has no navigation entry or per-user administrative SSO proxy.

## Future enablement (requires separate deployment approval)

- `PERSONAL_MEMORY_ENABLED=false` by default; enable explicitly only after preview
  acceptance. It does not inherit the shared vector-memory switch.
- Set `MEETING_MEMORY_TENANT_ID` and mount the persistent
  `MEETING_MEMORY_STATE_FILE` on the summary API and both workers, with appropriate
  restrictive UID permissions. The API needs the volume for admin corrections;
  previous deployments mounting it only on workers are insufficient for this UI.
- Update both workers and the summary API from the same release. No new frontend
  deployment is needed for the standalone internal admin page. If the feature is
  disabled, API data is denied and the admin page returns 404.
- Back up SQLite before enablement. Disabling the feature leaves data intact.
  No historical backfill or production writes are performed by this change.

## Remaining acceptance / limitations

- Tests use synthetic meetings and model stubs: real-model multi-meeting extraction
  accuracy and a complete production delivery cycle still need acceptance.
- Extremely long transcripts (>60,000 characters) or missing dates return
  `needs_review`; failed extractions can be retried as personal-memory tasks only.
  No automatic backfill, admin retry UI, or failure-notification email is included.
- A model can still misunderstand a source statement; exact evidence validation
  does not prove semantic correctness. Review candidates and manual corrections
  are part of the design, not a guarantee of zero errors.
- Markdown attachment checkboxes remain static. Changes made in the admin page
  update future memory, not attachments already emailed.
