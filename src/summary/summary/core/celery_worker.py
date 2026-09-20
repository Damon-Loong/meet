"""Celery workers."""

# ruff: noqa: PLR0913

import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
import sentry_sdk
from celery import Celery, signals
from celery.utils.log import get_task_logger
from openai.types.audio import Transcription
from requests import exceptions

from summary.core.analytics import MetadataManager, get_analytics
from summary.core.config import get_settings
from summary.core.docs_service import create_document_in_lasuite_docs
from summary.core.email_service import send_meeting_documents
from summary.core.file_service import (
    CorruptedAudioFile,
    FileService,
    FileServiceException,
    TranscribeError,
)
from summary.core.llm_service import LLMException, LLMObservability, LLMService
from summary.core.locales import get_locale
from summary.core.models import (
    PushToDocsBaseConfig,
    RecordingMetadata,
    SummarizeTaskJob,
    TranscribeTaskJob,
)
from summary.core.prompt import (
    FORMAT_NEXT_STEPS,
    FORMAT_PLAN,
    PROMPT_SYSTEM_CLEANING,
    PROMPT_SYSTEM_NEXT_STEP,
    PROMPT_SYSTEM_PART,
    PROMPT_SYSTEM_PLAN,
    PROMPT_SYSTEM_TLDR,
    PROMPT_USER_PART,
    PROMPT_SYSTEM_FINAL_SUMMARY,
    PROMPT_SYSTEM_SEGMENT_EXTRACT,
    PROMPT_USER_FINAL_SUMMARY,
    PROMPT_USER_SEGMENT_EXTRACT,
)
from summary.core.shared_models import (
    SummarizeWebhookFailurePayload,
    SummarizeWebhookSuccessPayload,
    TranscribeWebhookFailurePayload,
    TranscribeWebhookSuccessPayload,
    WhisperXResponse,
    webhook_payload_adapter,
)
from summary.core.transcript_formatter import TranscriptFormatter
from summary.core.user_assign import resolve_speaker_identities
from summary.core.webhook_service import (
    call_webhook_v2,
)

settings = get_settings()
analytics = get_analytics()

metadata_manager = MetadataManager()

logger = get_task_logger(__name__)

celery = Celery(
    __name__,
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    broker_connection_retry_on_startup=True,
    # To store the tasks args too in results and make the
    # V2 API work
    result_extended=True,
)

celery.config_from_object("summary.core.celery_config")

if settings.sentry_dsn and settings.sentry_is_enabled:

    @signals.celeryd_init.connect
    def init_sentry(**_kwargs):
        """Initialize sentry."""
        sentry_sdk.init(dsn=settings.sentry_dsn, enable_tracing=True)


file_service = FileService()


def transcribe_audio(
    *,
    task_id: str,
    language: str,
    cloud_storage_url: str,
    raises: bool = False,
):
    """Transcribe an audio file using WhisperX.

    Downloads the audio from a cloud storage URL, sends it to
    WhisperX for transcription, and tracks metadata throughout the process.

    Returns the transcription object, or None if the file could not be retrieved.
    """
    logger.info("Initiating WhisperX client")

    # Transcription
    try:
        with file_service.prepare_audio_file(
            cloud_storage_url=cloud_storage_url,
        ) as (audio_file, metadata):
            metadata_manager.track(task_id, {"audio_length": metadata["duration"]})

            # Compute language parameter
            if language is None:
                language = settings.whisperx_default_language
                logger.info(
                    "No language specified, using default from settings: %s",
                    (language or "auto-detect"),
                )
            else:
                logger.info(
                    "Querying transcription in '%s' language",
                    language,
                )

            # Call remote service for transcription
            transcription_start_time = time.time()

            api_key = settings.whisperx_api_key.get_secret_value()
            base_url = settings.whisperx_base_url

            # We use a manual call to the transcripion endpoint, and we do not
            # directly use the OpenAI lib for this.
            # This is because, depending on the requested response format,
            # the OpenAI lib will cast the response to a different dataclass,
            # which can result in stripping out keys & data that we are interested in.
            # This is in particular true for word_segments and words.
            # WhisperX response is slightly different from OpenAI STT endpoints
            # response.
            # At the same time "diarized_json" should be the value
            # provided to STT endpoints in our context.
            url = urljoin(base_url.rstrip("/") + "/", "audio/transcriptions")
            transcription_data = {
                "model": settings.whisperx_asr_model,
                "language": language,
                "timestamp_granularities": ["word", "segment"],
                "response_format": settings.whisperx_response_format,
            }
            if settings.whisperx_max_completion_tokens:
                transcription_data["max_completion_tokens"] = (
                    settings.whisperx_max_completion_tokens
                )

            res = requests.post(
                url,
                data=transcription_data,
                files={"file": audio_file},
                headers={"Authorization": f"Bearer {api_key}"},
                # Mimic OpenAI's timeout settings
                timeout=(60, 10 * 60),
            )
            if res.status_code == 400:
                logger.info(
                    "WhisperX transcription failed, "
                    "likely due to a corrupted audio file: %s",
                    res.text,
                )
                raise CorruptedAudioFile("WhisperX coudln't decode the audio file.")

            try:
                res.raise_for_status()
            except requests.exceptions.HTTPError:
                logger.exception("WhisperX transcription failed")
                # We reraise the error so that it can be retried by celery
                raise

            transcription_json: dict[str, Any] = res.json()
            # We remove the "usage" key from the transcription_json dictionary
            # as it may cause issues with parsing inside the Transcription model
            # Some API don't share the exact same structure for the "usage" key
            transcription_json.pop("usage", None)

            # We force the use of the Transcription model here
            # to avoid changing too much code for now.
            # Note that it should be WhisperXResponse instead.
            transcription = Transcription.model_validate(
                # We add a dummy "text" to make the model validate,
                # Some API responses lack the "text" key.
                {"text": "", **transcription_json},
                extra="allow",
                strict=False,
            )

            # Logging
            transcription_duration = round(time.time() - transcription_start_time, 2)
            metadata_manager.track(
                task_id,
                {"transcription_time": transcription_duration},
            )
            logger.info(
                "Transcription received in %.2f seconds.", transcription_duration
            )
            logger.debug("Transcription: \n %s", transcription)

    except FileServiceException as e:
        # For v2 pipeline we want failures not silent errors like this
        if raises:
            raise e
        redacted_cloud_storage_url = (
            cloud_storage_url.split("?", 1)[0] if cloud_storage_url else None
        )
        logger.exception(
            ("Unexpected error while preparing file %s "),
            redacted_cloud_storage_url,
        )
        return None

    metadata_manager.track_transcription_metadata(task_id, transcription)
    return transcription


def resolve_speaker_identities_and_apply_to(
    *,
    transcription: WhisperXResponse,
    recording_metadata: RecordingMetadata,
    task_id,
    participant_metadata: dict | None = None,
) -> WhisperXResponse:
    """Assign users to detected speakers and rewrite the transcriptions.

    Args:
        transcription: output of meet-whisperx after transcription and diarization
        recording_metadata: Metadata of the recording
        task_id: current task id, for logging purposes
    """
    logger.debug(
        "recording_start_dt: %s ; recording_end_dt: %s",
        recording_metadata.started_at,
        recording_metadata.ended_at,
    )

    logger.debug("Running resolve_speaker_identities")
    try:
        if participant_metadata:
            metadata = participant_metadata
        elif recording_metadata.cloud_storage_url:
            metadata = file_service.read_cloud_storage_json(
                recording_metadata.cloud_storage_url
            )
        else:
            return transcription
        speaker_mapping = resolve_speaker_identities(
            metadata,
            transcription.model_dump(),
            recording_metadata.started_at,
            recording_metadata.ended_at,
        )
        new_transcription = speaker_mapping.apply_to(transcription.model_dump())
        return WhisperXResponse.model_validate(new_transcription)

    except FileServiceException as exc:
        logger.error(
            "Error reading metadata for task %s; skipping speaker assignment."
            " Error: %s",
            task_id,
            exc,
        )
        return transcription

    except Exception as exc:
        logger.exception(
            "resolve_speaker_identities failed for task %s; skipping"
            " speaker assignment. Error: %s",
            task_id,
            exc,
        )
        return transcription


def format_transcript(
    transcription,
    context_language: str | None,
    language: str,
    download_link: str | None,
    form_link: str | None,
    title: str | None = None,
    recording_metadata: RecordingMetadata | None = None,
    participant_metadata: dict | None = None,
) -> str:
    """Format a transcription into readable content with a title.

    Resolves the locale from context_language / language, then uses
    TranscriptFormatter to produce markdown content and a title.

    Returns a (content, title) tuple.
    """
    locale = get_locale(context_language, language)
    formatter = TranscriptFormatter(locale)

    return formatter.format(
        transcription,
        download_link=download_link,
        form_link=form_link,
        title=title,
        recording_metadata=recording_metadata,
        participant_metadata=participant_metadata,
    )


def format_actions(llm_output: dict, participants: list[str] | None = None) -> str:
    """Format explicit action items without inventing owners or deadlines."""
    lines = [
        "## 每个人的 To-do List",
        "",
        "| 负责人 | 任务 | 时间要求 | 归属依据 |",
        "| --- | --- | --- | --- |",
    ]
    pending = []
    assigned_people = set()

    def cell(value: str) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").strip()

    for action in llm_output.get("actions", []):
        title = cell(action.get("title", ""))
        if not title:
            continue
        assignees = action.get("assignees", [])
        due_date = action.get("due_date") or "未明确"
        if assignees:
            for assignee in assignees:
                assigned_people.add(str(assignee).casefold())
                lines.append(
                    f"| {cell(assignee)} | {title} | {cell(due_date)} | 会议中明确指派 |"
                )
        else:
            pending.append((title, due_date))
    for participant in participants or []:
        if participant.casefold() not in assigned_people:
            lines.append(
                f"| {cell(participant)} | 本次未识别到明确分配的待办 | - | - |"
            )
    if len(lines) == 4:
        lines.append("| - | 本次未识别到明确分配的待办 | - | - |")
    if pending:
        lines.extend(["", "## 负责人待确认", ""])
        lines.extend(f"- {title}（时间要求：{due_date}）" for title, due_date in pending)
    return "\n".join(lines)


def format_summary_document(*, transcript: str, summary: str, title: str) -> str:
    """Combine authoritative transcript metadata with the generated summary."""

    disclaimer = (
        "> 本文档由 AI 根据会议转写自动生成，可能存在遗漏或误差；"
        "重要决策、人名、数据和行动项请以人工确认为准。"
    )

    # The current summarization prompt generates the complete document. Keep
    # the AI result intact instead of prepending a second title and metadata
    # block. The fallback below remains for summaries created by the legacy
    # prompt chain.
    if re.search(r"^# .+｜会议纪要\s*$", summary, flags=re.MULTILINE):
        return f"{summary.strip()}\n\n---\n\n{disclaimer}\n"

    def section(name: str) -> str:
        match = re.search(
            rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)",
            transcript,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else "未记录"

    document_title = title.removesuffix("的会议总结")
    english_title = re.fullmatch(
        r'Meeting "(.+)" on \d{4}-\d{2}-\d{2} at \d{2}:\d{2}', document_title
    )
    meeting_title = english_title.group(1) if english_title else document_title

    return (
        f"# {meeting_title}｜会议总结\n\n"
        "## 会议概览\n\n"
        f"{section('会议概览')}\n\n"
        "## 参会人员\n\n"
        f"{section('参会人员')}\n\n"
        "## 材料范围\n\n"
        "- 本总结根据会议语音转写内容生成。\n\n"
        f"{summary.strip()}\n\n"
        "---\n\n"
        f"{disclaimer}\n"
    )


def summarize_transcription_internals(
    *, distinct_id: str, transcript: str, session_id: str
) -> str:
    """Generate a summary from the provided transcription text.

    1. Splits the timestamped transcript into four chronological segments.
    2. Uses the LLM to extract reliable facts from each segment.
    3. Uses one final LLM call to reconcile and write the complete Markdown report.
    """
    logger.info(
        "Starting summarization task | Owner: %s",
        distinct_id,
    )

    user_has_tracing_consent = analytics.is_feature_enabled(
        "summary-tracing-consent", distinct_id=distinct_id
    )

    # NOTE: We must instantiate a new LLMObservability client for each task invocation
    # because the masking function needs to be user-specific. The masking function is
    # baked into the Langfuse client at initialization time, so we can't reuse
    # a singleton client. This is a performance trade-off we accept to ensure per-user
    # privacy controls in observability traces.
    llm_observability = LLMObservability(
        user_has_tracing_consent=user_has_tracing_consent,
        session_id=session_id,
        user_id=distinct_id,
    )
    llm_service = LLMService(llm_observability=llm_observability)

    transcript_heading = re.search(
        r"^## 逐字转录\s*$", transcript, flags=re.MULTILINE
    )
    if transcript_heading:
        meeting_context = transcript[: transcript_heading.start()].strip()
        transcript_body = transcript[transcript_heading.end() :].strip()
    else:
        meeting_context = "会议基础信息未单独提供，请仅使用转写中明确出现的信息。"
        transcript_body = transcript.strip()

    # Keep timestamps and speaker labels while removing Markdown decoration and
    # empty lines. This reduces input size without discarding evidence needed by
    # the final model to attribute decisions and action items.
    compact_lines = []
    for line in transcript_body.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(
            r"^-\s*\*\*\[([^]]+)]\s*([^：]+)：\*\*\s*",
            r"[\1][\2] ",
            line,
        )
        compact_lines.append(line)

    # Four chronological chunks substantially reduce repeated context and model
    # calls compared with the former topic-by-topic workflow. Calls remain
    # sequential to avoid increasing GPU peak memory on self-hosted models.
    segment_count = min(4, max(1, len(compact_lines)))
    total_chars = sum(len(line) + 1 for line in compact_lines)
    target_chars = max(1, total_chars // segment_count)
    segments: list[str] = []
    current: list[str] = []
    current_chars = 0
    for line in compact_lines:
        if (
            current
            and current_chars >= target_chars
            and len(segments) < segment_count - 1
        ):
            segments.append("\n".join(current))
            current = []
            current_chars = 0
        current.append(line)
        current_chars += len(line) + 1
    if current:
        segments.append("\n".join(current))

    segment_extracts = []
    for index, segment in enumerate(segments, start=1):
        logger.info("Extracting transcript segment %s/%s", index, len(segments))
        prompt = PROMPT_USER_SEGMENT_EXTRACT.format(
            meeting_context=meeting_context,
            index=index,
            total=len(segments),
            segment=segment,
        )
        extracted = llm_service.call(
            PROMPT_SYSTEM_SEGMENT_EXTRACT,
            prompt,
            name=f"segment-{index}",
        )
        segment_extracts.append(
            f"## 第 {index}/{len(segments)} 段提取结果\n\n{extracted.strip()}"
        )

    logger.info("Transcript segments extracted")

    final_prompt = PROMPT_USER_FINAL_SUMMARY.format(
        meeting_context=meeting_context,
        segment_extracts="\n\n".join(segment_extracts),
    )
    summary = llm_service.call(
        PROMPT_SYSTEM_FINAL_SUMMARY,
        final_prompt,
        name="final-summary",
    )
    logger.info("Final summary generated")

    llm_observability.flush()
    logger.debug("LLM observability flushed")

    return summary


##################################################################################
# Tasks v2
##################################################################################


def _should_push_to_docs(
    payload: TranscribeTaskJob | SummarizeTaskJob,
) -> bool:
    """Determines if the transcription should be pushed to docs.

    Based on the payload and settings.
    """
    if not payload.push_to_docs_config:
        reason = "Push to docs is not requested in the payload"
    elif not settings.is_lasuite_docs_integration_enabled:
        reason = "Docs integration is disabled"
    elif not settings.get_authorized_tenant(
        tenant_id=payload.tenant_id
    ).allowed_push_to_docs:
        reason = "Tenant is not allowed to push to docs"
    else:
        return True

    logger.info("Push to docs is not requested: %s", reason)
    return False


def _should_auto_create_summary(payload: TranscribeTaskJob) -> bool:
    """Determines if the transcription should have an auto-created summary.

    Based on the payload and settings.
    """
    if (
        payload.push_to_docs_config is None
        or not payload.push_to_docs_config.auto_create_summary
    ):
        reason = "Auto create summary is not requested in the payload"
    elif not settings.is_summary_enabled:
        reason = "Summary feature is disabled"
    else:
        return True

    logger.info("Auto create summary is not requested: %s", reason)
    return False


@celery.task(
    max_retries=3,
    queue=settings.call_webhook_queue_v2,
    autoretry_for=[exceptions.RequestException],
)
def call_webhook_v2_task(
    payload: dict,
    tenant_id: str,
):
    """Calls a webhook asynchrously (retry handled by celery)."""
    call_webhook_v2(
        payload=webhook_payload_adapter.validate_python(payload), tenant_id=tenant_id
    )


@celery.task(
    bind=True,
    autoretry_for=[
        exceptions.RequestException,
    ],
    max_retries=settings.celery_max_retries,
    queue=settings.transcribe_queue_v2,
)
def process_audio_transcribe_v2_task(
    self,
    payload: dict,
):
    """Process an audio file by transcribing it.

    This Celery task orchestrates:
    1. Audio transcription via WhisperX
    2. Store transcript result on S3
    3. Webhook submission

    Args:
        self: Celery task instance (passed on with bind=True)
        payload: Serialized dictionary of TranscribeSummarizeTaskCreationV2
    """
    payload = TranscribeTaskJob.model_validate(payload)
    logger.info(
        "Transcribing for object received | Owner: %s",
        payload.user_sub,
    )

    job_id = self.request.id

    try:
        transcription_res = WhisperXResponse(
            **transcribe_audio(  # type: ignore
                task_id=job_id,
                cloud_storage_url=payload.cloud_storage_url,
                language=payload.language,
                raises=True,
            ).model_dump()
        )
    except TranscribeError as e:
        failure_payload = TranscribeWebhookFailurePayload(
            job_id=job_id,
            error_code=e.error_code,
        )
        call_webhook_v2_task.apply_async(
            args=[failure_payload.model_dump(), payload.tenant_id]
        )
        return failure_payload.model_dump()

    participant_metadata = None
    if payload.metadata is not None:
        participant_metadata = {"participants": payload.metadata.participants}
        if payload.metadata.cloud_storage_url:
            try:
                collected_metadata = file_service.read_cloud_storage_json(
                    payload.metadata.cloud_storage_url
                )
                collected_metadata.setdefault(
                    "participants", payload.metadata.participants
                )
                participant_metadata = collected_metadata
            except Exception as exc:
                logger.warning("Unable to read meeting metadata: %s", exc)

    # Assign speakers and rewrite transcription/diarization output
    if (
        settings.is_resolve_speaker_identities_enabled
        and payload.metadata is not None
        and payload.metadata.cloud_storage_url
    ):
        try:
            transcription_res = resolve_speaker_identities_and_apply_to(
                transcription=transcription_res,
                recording_metadata=payload.metadata,
                task_id=job_id,
                participant_metadata=participant_metadata,
            )
        except Exception as e:
            logger.error(f"Failed to resolve speaker identities, skipping: {e}")

    transcript_config = payload.push_to_docs_config
    content = format_transcript(
        transcription_res.model_dump(),
        payload.context_language,
        payload.language,
        transcript_config.download_link if transcript_config else None,
        transcript_config.form_link if transcript_config else None,
        title=transcript_config.title if transcript_config else None,
        recording_metadata=payload.metadata,
        participant_metadata=participant_metadata,
    )

    should_push_to_docs = _should_push_to_docs(payload)
    # We do it synchronously for now
    if should_push_to_docs:
        if payload.push_to_docs_config is None:
            raise ValueError("Push to docs config is missing")

        create_document_in_lasuite_docs(
            content=content,
            title=payload.push_to_docs_config.title,
            email=payload.push_to_docs_config.user_email,
            sub=payload.user_sub,
        )

    # Summary generation is independent from La Suite Docs. This allows
    # self-hosted deployments to deliver transcript/summary by email only.
    if _should_auto_create_summary(payload):
        if payload.push_to_docs_config is None:
            raise ValueError("Summary delivery configuration is missing")

        locale = get_locale(payload.context_language, payload.language)
        summarize_v2_task.apply_async(
            args=[
                SummarizeTaskJob(
                    received_at=datetime.now(timezone.utc),
                    tenant_id=payload.tenant_id,
                    user_sub=payload.user_sub,
                    user_email=payload.user_email,
                    recipient_emails=payload.recipient_emails,
                    push_to_docs_config=PushToDocsBaseConfig(
                        user_email=payload.push_to_docs_config.user_email,
                        title=locale.summary_title_template.format(
                            title=payload.push_to_docs_config.title
                        ),
                    ),
                    content=content,
                ).model_dump()
            ],
        )

    file_service.store_transcript(
        transcript=transcription_res,
        job_id=job_id,
    )

    success_payload = TranscribeWebhookSuccessPayload(
        job_id=job_id,
        transcription_data_url=file_service.get_transcript_signed_url(job_id),
    )
    call_webhook_v2_task.apply_async(
        args=[success_payload.model_dump(), payload.tenant_id]
    )
    metadata_manager.capture(job_id, settings.posthog_transcript_success)

    return success_payload.model_dump()


@signals.task_prerun.connect(sender=process_audio_transcribe_v2_task)
def task_started_transcript(task_id=None, task=None, args=None, **kwargs):
    """Signal handler called before task execution begins."""
    if args:
        metadata_manager.create(task_id, TranscribeTaskJob.model_validate(args[0]))


@signals.task_retry.connect(sender=process_audio_transcribe_v2_task)
def task_retry_handler_transcript(request=None, reason=None, einfo=None, **kwargs):
    """Signal handler called when task execution retries."""
    metadata_manager.retry(request.id)


@signals.task_failure.connect(sender=process_audio_transcribe_v2_task)
def handle_transcribe_v2_failed(  # noqa: PLR0917
    sender,
    task_id=None,
    exception=None,
    args=None,
    kwargs=None,
    traceback=None,
    einfo=None,
    **kw,
):
    """Handle the failure of transcribe_v2_task.

    Tracks the failure event in analytics and sends a failure webhook to the client.
    """
    logger.error(
        "Transcribe task %s failed, no more retries left, sending failure webhook.",
        task_id,
    )
    metadata_manager.capture(
        task_id,
        settings.posthog_transcript_failure,
        {"exception_type": type(exception).__name__},
    )
    call_webhook_v2_task.apply_async(
        args=[
            TranscribeWebhookFailurePayload(
                job_id=task_id,
                error_code="unknown_error",
            ).model_dump(),
            args[0]["tenant_id"],
        ]
    )


@celery.task(
    bind=True,
    autoretry_for=[LLMException, Exception],
    max_retries=settings.celery_max_retries,
    queue=settings.summarize_queue_v2,
)
def summarize_v2_task(
    self,
    payload: dict,
):
    """Generate a summary from the provided content.

    This Celery task performs the following operations:
    1. Run summary internals
    2. Sends the final summary via webhook.
    """
    payload = SummarizeTaskJob.model_validate(payload)
    summary = summarize_transcription_internals(
        distinct_id=payload.user_sub,
        transcript=payload.content,
        session_id=self.request.id,
    )
    summary = format_summary_document(
        transcript=payload.content,
        summary=summary,
        title=(
            payload.push_to_docs_config.title
            if payload.push_to_docs_config
            else "会议总结"
        ),
    )
    job_id = self.request.id
    file_service.store_summary(summary=summary, job_id=job_id)

    if payload.recipient_emails and payload.push_to_docs_config:
        send_meeting_documents(
            recipients=[str(email) for email in payload.recipient_emails],
            title=payload.push_to_docs_config.title,
            transcript=payload.content,
            summary=summary,
        )

    if _should_push_to_docs(payload):
        if payload.push_to_docs_config is None:
            raise ValueError("Push to docs config is missing")

        create_document_in_lasuite_docs(
            content=summary,
            title=payload.push_to_docs_config.title,
            email=payload.push_to_docs_config.user_email,
            sub=payload.user_sub,
        )

    success_payload = SummarizeWebhookSuccessPayload(
        job_id=job_id,
        summary_data_url=file_service.get_summary_signed_url(job_id),
    )
    call_webhook_v2_task.apply_async(
        args=[success_payload.model_dump(), payload.tenant_id]
    )
    metadata_manager.capture(job_id, settings.posthog_summary_success)

    return success_payload.model_dump()


@signals.task_prerun.connect(sender=summarize_v2_task)
def task_started_summary(task_id=None, task=None, args=None, **kwargs):
    """Signal handler called before task execution begins."""
    if args:
        metadata_manager.create(task_id, SummarizeTaskJob.model_validate(args[0]))


@signals.task_retry.connect(sender=summarize_v2_task)
def task_retry_handler_summary(request=None, reason=None, einfo=None, **kwargs):
    """Signal handler called when task execution retries."""
    metadata_manager.retry(request.id)


@signals.task_failure.connect(sender=summarize_v2_task)
def handle_summarize_v2_failed(  # noqa: PLR0917
    sender,
    task_id=None,
    exception=None,
    args=None,
    kwargs=None,
    traceback=None,
    einfo=None,
    **kw,
):
    """Handle the failure of summarize_v2_task.

    Tracks the failure event in analytics and sends a failure webhook to the client.
    """
    logger.warn(
        "Summary task %s failed, no more retries left, sending failure webhook.",
        task_id,
    )
    metadata_manager.capture(
        task_id,
        settings.posthog_summary_failure,
        {"exception_type": type(exception).__name__},
    )
    call_webhook_v2_task.apply_async(
        args=[
            SummarizeWebhookFailurePayload(
                job_id=task_id,
                error_code="unknown_error",
            ).model_dump(),
            args[0]["tenant_id"],
        ]
    )
