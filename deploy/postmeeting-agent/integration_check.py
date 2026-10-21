"""2026-10-20，wyy 新增：会后功能的隔离真实 API/邮件验收入口。

只使用合成会议数据、独立测试状态和显式测试邮箱。generate 不发邮件；
独立产物检查通过后才能用 deliver 复用真实 outbox 与单人邮件交付。
"""

import argparse
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

from summary.core.config import get_settings
from summary.core.postmeeting_processing import process
from summary.core.postmeeting_tasks import database, enqueue, handle_job


def main():
    """Keep synthetic generation and explicitly requested email delivery separate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["generate", "resume-generation", "deliver"])
    args = parser.parse_args()
    settings = get_settings()
    root = Path(settings.postmeeting_state_dir)
    email = os.environ.get("POSTMEETING_TEST_EMAIL", "").strip().lower()
    if (
        os.environ.get("POSTMEETING_TEST_MODE") != "true"
        or not email
        or "/test-" not in settings.postmeeting_host_state_dir
        or not Path(settings.meeting_memory_state_file).is_relative_to(root)
        or {x.lower() for x in settings.postmeeting_allowed_recipient_emails} != {email}
    ):
        raise RuntimeError("Explicit isolated test configuration required")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    runfile = root / "integration-run.json"
    bundlesfile = root / "integration-bundles.json"
    if args.stage == "generate":
        if runfile.exists():
            raise RuntimeError(
                "Test already started; inspect checkpoint instead of replaying"
            )
        run = uuid.uuid4().hex[:12]
        transcript = (
            f"# 合成数据验收 {run}\n"
            "测试员甲：本次全部是虚构测试数据，不代表真实业务。\n"
            "测试员甲：项目甲金额10，项目乙金额20，项目丙金额30，合计60。"
            "请测试员甲把这三个项目和金额做成Excel，包含合计公式，显著标注合成数据。\n"
            "测试员甲：请测试员甲另做三页PPT：第一页说明合成测试背景，"
            "第二页列出项目甲10、项目乙20、项目丙30及合计60，"
            "第三页总结只验证生成能力，不添加任何真实业务进展或结论。\n"
            "测试员甲：还有一个独立任务，请测试员甲制作本周各门店真实销售同比分析表。"
            "但是我们没有提供门店、本周和去年同期的真实销售数据，"
            "请明确说明缺少资料，不要编造数字；如交模板须显著标注待补数据。\n"
        )
        summary = (
            f"# 合成数据验收 {run}\n\n"
            "- 测试员甲：用项目甲10、项目乙20、项目丙30生成含合计公式的Excel。\n"
            "- 测试员甲：制作三页合成数据PPT，展示金额与合计60。\n"
            "- 测试员甲：真实销售同比分析缺少全部原始数据，不能编造。\n"
        )
        raw = {
            "tenant_id": settings.authorized_tenants[0].id,
            "content": transcript,
            "recipient_emails": [email],
            "media_recording_id": None,
            "push_to_docs_config": {"title": f"【测试】会后Agent合成验收 {run}"},
            "participants": [{"name": "测试员甲", "email": email}],
        }
        payload = SimpleNamespace(model_dump=lambda **_kw: raw)
        (root / "worker-heartbeat").touch(mode=0o600)
        delivery_key = "postmeeting-integration:" + run
        if not enqueue(settings, payload, summary, delivery_key):
            raise RuntimeError("Isolated handoff was not accepted")
        with database(settings) as db:
            row = db.execute(
                "SELECT j.* FROM jobs j JOIN handoffs h ON j.id=h.job WHERE h.delivery_key=?",
                (delivery_key,),
            ).fetchone()
            job = row["id"]
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job,))
        runfile.write_text(json.dumps({"job": job, "run": run}), encoding="utf-8")
        bundles = process(settings, job, json.loads(row["payload"]))
        bundlesfile.write_text(
            json.dumps(bundles, ensure_ascii=False), encoding="utf-8"
        )
        with database(settings) as db:
            db.execute(
                "UPDATE jobs SET status='delivering',result=? WHERE id=?",
                (json.dumps(bundles, ensure_ascii=False), job),
            )
        print(
            json.dumps(
                {
                    "stage": "generated",
                    "job": job,
                    "reports": len(bundles["u0"]["text"]),
                    "attachments": [
                        a["filename"] for a in bundles["u0"]["attachments"]
                    ],
                }
            )
        )
    elif args.stage == "resume-generation":
        # Explicit operator retry in synthetic testing only. Successful stages reuse
        # their controller checkpoints; no production worker replay is enabled.
        job = json.loads(runfile.read_text(encoding="utf-8"))["job"]
        with database(settings) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        if row["status"] != "delivering":
            raise RuntimeError("Only an undelivered synthetic job may be retried")
        bundles = process(settings, job, json.loads(row["payload"]))
        previous = root / "integration-bundles.before-retry.json"
        if not previous.exists():
            previous.write_bytes(bundlesfile.read_bytes())
        bundlesfile.write_text(
            json.dumps(bundles, ensure_ascii=False), encoding="utf-8"
        )
        with database(settings) as db:
            db.execute(
                "UPDATE jobs SET result=? WHERE id=?",
                (json.dumps(bundles, ensure_ascii=False), job),
            )
        print(
            json.dumps(
                {
                    "stage": "resumed",
                    "attachments": [
                        a["filename"] for a in bundles["u0"]["attachments"]
                    ],
                }
            )
        )
    else:
        validation = root / "validation" / "validation.json"
        checked = json.loads(validation.read_text(encoding="utf-8"))
        if not checked.get("passed"):
            raise RuntimeError("Independent artifact checks must pass before email")
        job = json.loads(runfile.read_text(encoding="utf-8"))["job"]
        with database(settings) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        handle_job(settings, row)
        with database(settings) as db:
            status = db.execute(
                "SELECT status FROM jobs WHERE id=?", (job,)
            ).fetchone()[0]
            recipients = [
                r["status"]
                for r in db.execute("SELECT status FROM recipients WHERE job=?", (job,))
            ]
        print(
            json.dumps(
                {
                    "stage": "delivery",
                    "job_status": status,
                    "recipient_statuses": recipients,
                }
            )
        )
        if status != "done" or recipients != ["sent"]:
            raise RuntimeError(
                "Email outcome requires review; do not resend automatically"
            )


if __name__ == "__main__":
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO)
    main()
