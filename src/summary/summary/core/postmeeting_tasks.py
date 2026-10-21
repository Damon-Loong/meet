"""2026-10-20，wyy 新增：会后按用户自动执行任务与邮件交付的持久化调度.

正常纪要与补发纪要都通过本模块进入独立 worker。复用已有 DeliveryState
记录每封邮件；纪要未生成时不接管原有转录先发流程。关闭开关时不初始化。
"""

import fcntl
import hashlib
import json
import logging
import os
import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from summary.core.delivery_state import DeliveryState
from summary.core.postmeeting_processing import candidates, process

logger = logging.getLogger(__name__)


@contextmanager
def database(settings):
    """Open a short transaction in the separate private execution outbox."""
    root = Path(settings.postmeeting_state_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(root / "outbox.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT, created REAL NOT NULL, updated REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS handoffs (
            delivery_key TEXT PRIMARY KEY, job TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS recipients (
            job TEXT NOT NULL, email TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY(job,email))""")
        db.commit()
        (root / "outbox.sqlite3").chmod(0o600)
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _reserve_delivery(mail, delivery_key, summary):
    """Reserve the original stage without reclaiming sending or uncertain mail."""
    with mail.db() as db:
        db.execute(
            "INSERT OR IGNORE INTO deliveries(key,summary) VALUES (?,?)",
            (delivery_key, summary),
        )
        return db.execute(
            "UPDATE deliveries SET status='postmeeting' WHERE key=? AND status='ready'",
            (delivery_key,),
        ).rowcount


def _resume_handoff(settings, job, delivery_key, summary):
    """Repair an interrupted publish without replaying execution or uncertain mail."""
    mail = DeliveryState(settings.meeting_memory_state_file)
    changed = _reserve_delivery(mail, delivery_key, summary)
    with database(settings) as db:
        if changed:
            db.execute(
                "UPDATE jobs SET status='pending',updated=? WHERE id=? "
                "AND status='handoff_wait' AND result IS NULL",
                (time.time(), job),
            )
        status = db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()[0]
    if status == "done" and mail.status(delivery_key) == "postmeeting":
        mail.finish(delivery_key, "sent")
    return True


def enqueue(settings, payload, summary, delivery_key, *, supplement=False):  # noqa: PLR0911
    """Durably hand off a usable summary, or preserve the original mail route."""
    if not settings.postmeeting_agent_enabled or not settings.email_delivery_enabled:
        return False
    root = Path(settings.postmeeting_state_dir)
    existing = None
    if (root / "outbox.sqlite3").exists():
        with database(settings) as db:
            existing = db.execute(
                "SELECT job FROM handoffs WHERE delivery_key=?", (delivery_key,)
            ).fetchone()
    # Sticky handoff survives outages and prevents duplicate group emails.
    if existing:
        return _resume_handoff(settings, existing["job"], delivery_key, summary)
    heartbeat = root / "worker-heartbeat"
    if not heartbeat.is_file() or time.time() - heartbeat.stat().st_mtime > 60:
        logger.warning(
            "Postmeeting worker unavailable; preserving original email route"
        )
        return False
    mail = DeliveryState(settings.meeting_memory_state_file)
    if mail.status(delivery_key) != "ready":
        return False  # Existing sender handles sent/uncertain states conservatively.
    raw = payload.model_dump(mode="json")
    addresses = sorted({str(x).strip().lower() for x in raw["recipient_emails"]})
    allowed = {
        email.strip().lower()
        for email in settings.postmeeting_allowed_recipient_emails
        if email.strip()
    }
    if not addresses or (allowed and not set(addresses).issubset(allowed)):
        logger.info(
            "Meeting outside postmeeting pilot scope; using original mail route"
        )
        return False
    data = {
        "tenant": raw["tenant_id"],
        "media_recording_id": raw.get("media_recording_id"),
        "source": str(
            raw.get("media_recording_id")
            or hashlib.sha256(raw["content"].encode()).hexdigest()
        ),
        "transcript": raw["content"],
        "summary": summary,
        "title": raw["push_to_docs_config"]["title"],
        "recipients": addresses,
        "participants": raw.get("participants", []),
        "supplement": bool(supplement),
    }
    identity = [
        data["tenant"],
        data["source"],
        data["transcript"],
        summary,
        addresses,
        "postmeeting-v2",
    ]
    job = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    with database(settings) as db:
        db.execute(
            "INSERT OR IGNORE INTO jobs(id,payload,created,updated) VALUES (?,?,?,?)",
            (job, json.dumps(data, ensure_ascii=False), time.time(), time.time()),
        )
        db.execute("INSERT OR IGNORE INTO handoffs VALUES (?,?)", (delivery_key, job))
    # Reserve the old group-mail stage after durable enqueue. The old sender treats
    # this non-ready state conservatively if someone disables the feature mid-flight.
    changed = _reserve_delivery(mail, delivery_key, summary)
    if not changed and mail.status(delivery_key) != "postmeeting":
        return False
    with database(settings) as db:
        status = db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()[0]
    if status == "done":
        mail.finish(
            delivery_key, "sent"
        )  # Identical document/users were already delivered.
    return True


def _interrupted(data):
    """Report interruption without replaying a partially executed task."""
    return {
        p["id"]: {
            "text": ["执行进程中断，为避免重复执行已停止自动重跑，请管理员核查。"],
            "attachments": [],
        }
        for p in candidates(data)
    }


def handle_job(settings, row):  # noqa: PLR0912, PLR0915 - ordered durable state transitions.
    """Execute once and reuse the existing transport ledger for individual delivery."""
    from summary.core.email_service import send_meeting_documents  # noqa: PLC0415

    data, job = json.loads(row["payload"]), row["id"]
    mail = DeliveryState(settings.meeting_memory_state_file)
    with database(settings) as db:
        stages = [
            r[0]
            for r in db.execute("SELECT delivery_key FROM handoffs WHERE job=?", (job,))
        ]
    if not stages:
        raise ValueError("Missing durable handoff")
    states = [mail.status(key) for key in stages]
    if all(status == "sent" for status in states):
        with database(settings) as db:
            db.execute(
                "UPDATE jobs SET status='done',updated=? WHERE id=?", (time.time(), job)
            )
        return
    if not any(status == "postmeeting" for status in states):
        # Outbox and mail ledger are separate databases. Wait if the publisher has
        # not reserved delivery yet; never race its possible original SMTP fallback.
        if time.time() - row["created"] > 60:
            with database(settings) as db:
                waiting = all(status == "ready" for status in states)
                db.execute(
                    "UPDATE jobs SET status=?,updated=? WHERE id=?",
                    ("handoff_wait" if waiting else "needs_review", time.time(), job),
                )
        return
    if row["result"]:
        bundles = json.loads(row["result"])
    elif row["status"] == "running":
        bundles = _interrupted(data)
    else:
        with database(settings) as db:
            db.execute(
                "UPDATE jobs SET status='running',updated=? WHERE id=?",
                (time.time(), job),
            )
        try:
            bundles = process(settings, job, data)
        except Exception:
            logger.error(
                "Postmeeting processing failed; preserving minutes; job=%s", job
            )
            bundles = {
                p["id"]: {
                    "text": [
                        "任务处理异常，未声称完成。会议纪要照常交付，请管理员核查。"
                    ],
                    "attachments": [],
                }
                for p in candidates(data)
            }
    with database(settings) as db:
        db.execute(
            "UPDATE jobs SET status='delivering',result=?,updated=? WHERE id=?",
            (json.dumps(bundles, ensure_ascii=False), time.time(), job),
        )
    for person in candidates(data):
        email, bundle = person["_email"], bundles[person["id"]]
        key = "postmeeting:" + job + ":" + hashlib.sha256(email.encode()).hexdigest()
        status = "sent"
        try:
            tenant = settings.get_authorized_tenant(tenant_id=data["tenant"])
            send_meeting_documents(
                recipients=[email],
                title=data["title"],
                transcript=data["transcript"],
                summary=data["summary"],
                media_recording_id=data["media_recording_id"],
                webhook_url=str(tenant.webhook_url),
                webhook_api_key=tenant.webhook_api_key.get_secret_value(),
                delivery_key=key,
                supplement=data["supplement"],
                task_result_text="\n\n".join(bundle["text"]),
                result_attachments=bundle["attachments"],
            )
        except Exception:
            status = (
                "delivery_unknown"
                if mail.status(key) in ("sending", "uncertain")
                else "preflight_failed"
            )
            logger.error("Postmeeting delivery requires review; job=%s", job)
        with database(settings) as db:
            db.execute(
                "INSERT INTO recipients VALUES (?,?,?) ON CONFLICT(job,email) "
                "DO UPDATE SET status=excluded.status",
                (job, email, status),
            )
    with database(settings) as db:
        failed = db.execute(
            "SELECT COUNT(*) FROM recipients WHERE job=? AND status!='sent'", (job,)
        ).fetchone()[0]
    if failed:
        with database(settings) as db:
            db.execute(
                "UPDATE jobs SET status='needs_review',updated=? WHERE id=?",
                (time.time(), job),
            )
        return
    # Confirm the original transport stage only after all personal sends succeed.
    # Import reminders only from a delivered document, preserving the new main behavior.
    # Lazy import avoids the summary worker -> postmeeting_tasks -> worker cycle.
    from summary.core.celery_worker import enqueue_personal_memory  # noqa: PLC0415

    enqueue_personal_memory(
        data["tenant"],
        data["transcript"],
        data["source"],
        data["participants"],
        data["summary"],
    )
    with database(settings) as db:
        stages = [
            r[0]
            for r in db.execute("SELECT delivery_key FROM handoffs WHERE job=?", (job,))
        ]
        for key in stages:
            if mail.status(key) == "postmeeting":
                mail.finish(key, "sent")
        db.execute(
            "UPDATE jobs SET status='done',updated=? WHERE id=?", (time.time(), job)
        )


def main():
    """Run only in the explicitly started optional worker; never in the summary API."""
    from summary.core.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if not settings.postmeeting_agent_enabled or not settings.email_delivery_enabled:
        return
    root = Path(settings.postmeeting_state_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stopped = threading.Event()

    def stop(_signum, _frame):
        stopped.set()
        (root / "worker-heartbeat").unlink(missing_ok=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (root / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def heartbeat():
            while not stopped.is_set():
                (root / "worker-heartbeat").touch(mode=0o600, exist_ok=True)
                stopped.wait(5)

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            while True:
                with database(settings) as db:
                    row = db.execute(
                        "SELECT * FROM jobs "
                        "WHERE status IN ('pending','running','delivering') "
                        "ORDER BY created LIMIT 1"
                    ).fetchone()
                if row:
                    try:
                        handle_job(settings, row)
                    except Exception:
                        logger.error(
                            "Postmeeting job requires operator review; job=%s",
                            row["id"],
                        )
                        with database(settings) as db:
                            db.execute(
                                "UPDATE jobs SET status='needs_review',updated=? "
                                "WHERE id=?",
                                (time.time(), row["id"]),
                            )
                time.sleep(5)
        finally:
            stopped.set()
            thread.join(timeout=6)
            (root / "worker-heartbeat").unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    main()
