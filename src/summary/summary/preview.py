"""Generate local review files through the real LLM, without delivery or storage."""

import argparse
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from unittest.mock import patch


def save_result(output, minutes, settings, timings, needs_review):
    """Persist private preview artifacts without sending them anywhere."""
    if needs_review:
        minutes = "> 待审核草稿：未通过证据校验，禁止作为正式纪要发送。\n\n" + minutes
    filename = "会议纪要-待审核.md" if needs_review else "会议纪要-新版.md"
    (output / filename).write_text(minutes, encoding="utf-8")
    (output / "run.json").write_text(
        json.dumps(
            {
                "model": settings.llm_model,
                "calls": timings,
                "delivery": False,
                "evidence_enabled": settings.summary_evidence_enabled,
                "needs_review": needs_review,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logging.info("Preview saved to %s", output)


def parse_args():
    """Read explicit local input and output paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--history-context",
        type=Path,
        help="Private retrieved history file for no-delivery preview only",
    )
    parser.add_argument(
        "--resume-audit",
        type=Path,
        help="Repair a private prior audit for the exact same transcript, then review",
    )
    parser.add_argument(
        "--evidence",
        action="store_true",
        help="Enable source-backed review (local process only)",
    )
    return parser.parse_args()


def preview_generator(default, audit_path):
    """Choose fresh generation or explicit, source-hash-checked audit resumption."""
    if not audit_path:
        return default
    from summary.core.evidence_summary import (  # noqa: PLC0415
        Audit,
        revise_evidence_summary,
    )

    previous = Audit.model_validate_json(audit_path.read_text(encoding="utf-8"))

    def resumed(transcript, call, **_kwargs):
        return revise_evidence_summary(transcript, previous, call)

    return resumed


def main():
    """Run only the summarization function; never enqueue a task or send email."""
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Set before importing settings. This preview has no analytics side effects.
    os.environ["POSTHOG_ENABLED"] = "false"
    os.environ["LANGFUSE_ENABLED"] = "false"
    os.environ["EMAIL_DELIVERY_ENABLED"] = "false"
    if args.evidence or args.resume_audit:
        os.environ["SUMMARY_EVIDENCE_ENABLED"] = "true"
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from summary.core import celery_worker  # noqa: PLC0415
    from summary.core.config import get_settings  # noqa: PLC0415
    from summary.core.evidence_summary import SummaryReviewRequired  # noqa: PLC0415
    from summary.core.llm_service import LLMService  # noqa: PLC0415

    original_call = LLMService.call
    settings = get_settings()
    timings = []

    def cached_call(service, system_prompt, user_prompt, name, response_format=None):
        request = {
            "model": settings.llm_model,
            "endpoint": settings.llm_base_url,
            "system": system_prompt,
            "user": user_prompt,
            "format": response_format,
            "language": settings.summary_output_language,
        }
        digest = hashlib.sha256(
            json.dumps(request, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        cache = args.output / f"{name}-{digest}.json"
        started = time.monotonic()
        cached = cache.exists()
        if cached:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            result = saved["response"]
            metadata = saved.get("metadata")
        else:
            result = original_call(
                service, system_prompt, user_prompt, name, response_format
            )
            metadata = service.last_response_metadata
            cache.write_text(
                json.dumps(
                    {"response": result, "metadata": metadata},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        elapsed = round(time.monotonic() - started, 2)
        logging.info("%s completed in %ss (cached=%s)", name, elapsed, cached)
        timings.append(
            {"call": name, "seconds": elapsed, "cached": cached, "metadata": metadata}
        )
        return result

    transcript = args.transcript.read_text(encoding="utf-8")
    audits = []

    def save_audit(audit):
        audits.append(audit)
        (args.output / "evidence-audit.json").write_text(
            audit.model_dump_json(indent=2), encoding="utf-8"
        )

    needs_review = False
    generator = preview_generator(
        celery_worker.generate_evidence_summary, args.resume_audit
    )
    with (
        patch.object(LLMService, "call", cached_call),
        patch.object(celery_worker, "generate_evidence_summary", generator),
    ):
        try:
            minutes = celery_worker.summarize_transcription_internals(
                distinct_id="local-preview",
                transcript=transcript,
                session_id="local-preview",
                audit_callback=save_audit,
                history_context=(
                    args.history_context.read_text(encoding="utf-8")
                    if args.history_context
                    else ""
                ),
            )
        except SummaryReviewRequired:
            needs_review = True
            minutes = (
                audits[-1].markdown
                if audits
                else "生成或核验未完成，需要人工审核；详细原因见本地调用记录。"
            )
    minutes = celery_worker.format_summary_document(
        transcript=transcript, summary=minutes, title="会议总结"
    )
    save_result(args.output, minutes, settings, timings, needs_review)
    if needs_review:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
