# AfB meeting-summary model configuration

## Current endpoint

The AfB deployment uses these non-secret summary-service settings:

```dotenv
LLM_BASE_URL=https://afb-model.mbmzone.com/afb-coca/v1
LLM_MODEL=afb-coca
```

The versioned settings fragment is
[`env.d/production.dist/summary-model`](../../env.d/production.dist/summary-model).
The former `/qwen3.8-27b/v1` route returned HTTP 404. Both the base URL and
the model argument must be updated together.

The summary service already reads these settings from its environment; no
application-code or prompt change is required for this endpoint migration.
This deployment-specific fragment does not change the generic development
defaults and is not loaded automatically by an existing deployment.

## Apply to an existing deployment

1. Back up the private deployment configuration and record the running summary
   worker's exact image/version. Check active, reserved and scheduled tasks
   before interrupting the worker.
2. Merge only `LLM_BASE_URL` and `LLM_MODEL` from the fragment into the existing
   summary-service environment file. **Do not replace the complete environment
   file with this two-setting fragment.** Preserve the existing authorized
   `LLM_API_KEY`, mail, storage, tenant and transcription settings.
3. Recreate the summary-generation worker with the same deployed application
   code, using the deployment's normal Compose/Kubernetes procedure. A process
   restart alone does not update Docker container environment variables.
4. Verify the values inside the recreated worker, confirm it is consuming its
   summary queue, and make a short model request using its normal configuration.
   Do not enqueue a historical meeting to test connectivity: that can resend mail.

If a mutable image tag now points at a newer image, pin the intended deployed
version before recreating the worker. Do not accidentally deploy new prompts or
transcription code while changing the model endpoint. Any private runtime backup
image may contain configuration and meeting data: never push it to a registry.

## Verification and rollback

On 2026-09-28, the new route's authenticated `/models` endpoint returned HTTP 200
and listed `afb-coca`. After recreating the production summary worker with the
existing application code, a short request returned `接口正常`. Other services
were not recreated and no historical meeting email was manually resent.

This verifies connectivity and runtime configuration, not the factual accuracy
of generated minutes or the full recording-to-email delivery chain. Concise
minutes and meeting-memory changes remain separate work and are not included
in this configuration update.

For rollback, restore the backed-up private settings and recreate the same
worker/image after checking running tasks. The former route was returning 404,
so reverting to it is not itself a recovery of model availability.

Never commit actual environment files, API keys, administrator credentials,
meeting transcripts, generated private minutes, or runtime backup images.
