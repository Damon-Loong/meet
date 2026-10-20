# Summary source reconciliation — 2026-10-20

The maintained repository is `Damon-Loong/meet`, branch `main`. The server
checkout is `/data/meet-main`; deployment configuration is maintained separately
at `/data/meet-deploy/compose.yaml`.

This reconciliation integrates the `codex/concise-meeting-summary` history and
the previously deployed patches for meeting-source metadata, confirmed ASR
hotwords, and bounded delivery validation with private diagnostic records.
The summary Python package was compared file-by-file with the running image
`lasuite-meet/summary:delivery-20261019` before integration.

## Existing image provenance

The running image was built incrementally, not from a single clean Git commit:

- Summary functionality through `d4a23e3d` (summary-derived email titles).
- `metadata-20261014`: reminder meeting titles and source metadata.
- `hotwords-20261019`: configurable confirmed vocabulary hints for MOSS.
- `delivery-20261019`: advisory punctuation checks and private review audits.

Updating the source checkout does not rebuild or restart that image. This
reconciliation must not replay meetings, resend email, or modify memory/task
state. Secrets, production state, recordings and private recovery artifacts are
not source files and must not be committed.

## Future development

Start from current `main`, use a feature branch, and merge tested changes before
building a release. Record the exact source commit and image digest for each
new release. Do not overwrite current production configuration with development
defaults. A future rebuild still requires deployment configuration and dependency
verification; Python source equality alone is not a complete image rebuild test.
