"""2026-10-20，wyy 新增：会后按用户执行任务的证据、归属和产物处理.

负责从现有纪要和转录识别明确任务，经 dsh 执行后返回每位用户结果。
调度和邮件使用独立 outbox 及已有 DeliveryState，本文件不直接发送邮件。
"""

import hashlib
import json
import time
from pathlib import Path

from summary.core.agent_runner import run_agent
from summary.core.artifact_validation import validate_artifacts
from summary.core.postmeeting_prompts import EXECUTE, EXTRACT


def candidates(data):
    """Map exact roster email matches to fixed delivery addresses."""
    roster = data.get("participants", [])
    result = []
    for index, email in enumerate(data["recipients"]):
        names = {
            str(p.get("name", "")).strip()
            for p in roster
            if isinstance(p, dict)
            and str(p.get("email", "")).strip().lower() == email
            and str(p.get("name", "")).strip()
        }
        name = next(iter(names)) if len(names) == 1 else ""
        result.append({"id": f"u{index}", "name": name, "_email": email})
    # Same display name across multiple accounts is not a unique identity.
    counts = {p["name"]: sum(q["name"] == p["name"] for q in result) for p in result}
    for person in result:
        if person["name"] and counts[person["name"]] > 1:
            person["name"] = ""
    return result


def process(settings, job, data):  # noqa: PLR0912, PLR0915 - sequential evidence/execution gates.
    """Execute validated meeting tasks and return recipient-specific reports."""
    people = candidates(data)
    visible = [{"id": p["id"], "name": p["name"]} for p in people if p["name"]]
    deadline = time.monotonic() + settings.postmeeting_batch_timeout_seconds

    def remaining():
        seconds = min(
            settings.postmeeting_task_timeout_seconds, int(deadline - time.monotonic())
        )
        if seconds <= 0:
            raise TimeoutError("Batch time budget exhausted")
        return seconds

    bundles = {p["id"]: {"text": [], "attachments": []} for p in people}
    if len(data["transcript"]) > 300000:
        for value in bundles.values():
            value["text"].append(
                "材料超过第一版自动执行大小限制，未调用模型；需要人工缩小任务资料范围。"
            )
        return bundles
    if not visible:
        for value in bundles.values():
            value["text"].append(
                "需要确认：参会者姓名与收件账号缺少唯一对应，未自动执行任务。"
            )
        return bundles
    try:
        extraction = run_agent(
            settings,
            job,
            "extract",
            EXTRACT,
            {
                "candidates": visible,
                "minutes": data["summary"],
                "transcript": data["transcript"],
            },
            remaining(),
        )
        tasks = extraction.get("tasks")
        if not isinstance(tasks, list) or len(tasks) > 12:
            raise ValueError("Invalid task extraction")
    except Exception as exc:
        for value in bundles.values():
            value["text"].append(
                f"任务识别未完成（{type(exc).__name__}）。会议纪要仍正常交付；未声称任务已完成。"
            )
        return bundles
    by_id = {p["id"]: p for p in people}
    seen = set()
    unresolved = []
    for task in tasks:
        if not isinstance(task, dict):
            unresolved.append("模型返回了无效任务，未自动执行。")
            continue
        description = task.get("description", "")
        quote, owners = task.get("quote", ""), task.get("owner_ids", [])
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 2000
        ):
            unresolved.append("任务描述无效，未自动执行。")
            continue
        if task.get("deliverable") not in ("xlsx", "pptx", "text"):
            unresolved.append(description + "：交付格式不明确，未执行。")
            continue
        if (
            not isinstance(quote, str)
            or len(quote.strip()) < 4
            or quote not in data["transcript"]
            or not isinstance(owners, list)
            or any(not isinstance(x, str) for x in owners)
        ):
            unresolved.append(description + "：原文证据或归属格式无效，未执行。")
            continue
        owners = list(dict.fromkeys(owners))
        # Conservatively require a unique registered name in the quoted evidence.
        if (
            not owners
            or task.get("ambiguity")
            or any(
                x not in by_id or not by_id[x]["name"] or by_id[x]["name"] not in quote
                for x in owners
            )
        ):
            unresolved.append(description + "：责任人尚需确认，未执行。")
            continue
        signature = hashlib.sha256(
            json.dumps(
                [description, quote, sorted(owners)], ensure_ascii=False
            ).encode()
        ).hexdigest()
        if signature in seen:
            continue
        seen.add(signature)
        attachments = []
        try:
            result = run_agent(
                settings,
                job,
                "task-" + signature,
                EXECUTE,
                {
                    "task": task,
                    "minutes": data["summary"],
                    "transcript": data["transcript"],
                },
                remaining(),
            )
            status = result.get("status")
            if status not in (
                "completed",
                "partial",
                "blocked_missing_data",
                "needs_confirmation",
                "failed",
            ):
                raise ValueError("Invalid execution status")
            for field in (
                "missing_information",
                "unresolved_requirements",
                "checks_performed",
            ):
                if not isinstance(result.get(field), list) or any(
                    not isinstance(x, str) for x in result[field]
                ):
                    raise ValueError("Invalid execution report")
            text = result.get("result_text")
            if not isinstance(text, str) or not text.strip() or len(text) > 20000:
                raise ValueError("Missing result explanation")
            if any(
                len(result[field]) > 100 or any(len(x) > 2000 for x in result[field])
                for field in (
                    "missing_information",
                    "unresolved_requirements",
                    "checks_performed",
                )
            ):
                raise ValueError("Execution report too large")
            if status in ("completed", "partial"):
                attachments = validate_artifacts(
                    result["_output_dir"],
                    result.get("artifacts", []),
                    settings.postmeeting_attachment_limit_bytes,
                )
                expected = task.get("deliverable")
                allowed_types = {
                    "xlsx": {".xlsx", ".pdf", ".txt", ".md", ".csv"},
                    "pptx": {".pptx", ".pdf", ".txt", ".md"},
                    "text": {".pdf", ".txt", ".md", ".csv"},
                }[expected]
                if any(
                    Path(a["filename"]).suffix.lower() not in allowed_types
                    for a in attachments
                ):
                    raise ValueError("Artifact outside assigned deliverable scope")
                if (
                    status == "completed"
                    and expected in ("xlsx", "pptx")
                    and not any(
                        a["filename"].lower().endswith("." + expected)
                        for a in attachments
                    )
                ):
                    raise ValueError("Expected Office deliverable missing")
                if status == "completed" and (
                    result["missing_information"]
                    or result["unresolved_requirements"]
                    or not result["checks_performed"]
                ):
                    status = "partial"
            labels = {
                "completed": "已生成成果（内容请核对）",
                "partial": "部分完成 / 草稿",
                "blocked_missing_data": "材料不足",
                "needs_confirmation": "需要确认",
                "failed": "执行失败",
            }
            report = description + "\n状态：" + labels[status] + "\n" + text
            for field, label in [
                ("missing_information", "缺少材料"),
                ("unresolved_requirements", "尚未完成"),
            ]:
                if result[field]:
                    report += "\n" + label + "：" + "；".join(result[field])
        except Exception as exc:
            attachments = []
            report = (
                description
                + f"\n未完成（{type(exc).__name__}）。未通过执行或产物检查，"
                + "未附上未经验证的文件。"
            )
        for owner in owners:
            bundles[owner]["text"].append(report)
            bundles[owner]["attachments"].extend(attachments)
    for person in people:
        value = bundles[person["id"]]
        if not value["text"]:
            value["text"].append(
                "本次未识别到可明确归属并自动执行的本人任务。"
                if person["name"]
                else "需要确认：本收件账号与参会者姓名缺少唯一对应，未自动分配任务。"
            )
        if unresolved:
            value["text"].append("会议中尚需确认的任务：\n" + "\n".join(unresolved))
        # Never let verbose model output prevent delivery of the original minutes.
        if len("\n\n".join(value["text"])) > 90000:
            value["text"] = [
                "\n\n".join(value["text"])[:89000]
                + "\n（说明过长已截断，需管理员核查完整记录。）"
            ]
        # Enforce total email limit across every task, not only each artifact set.
        unique = {a["path"]: a for a in value["attachments"]}
        value["attachments"] = list(unique.values())
        if (
            sum(Path(a["path"]).stat().st_size for a in value["attachments"])
            > settings.postmeeting_attachment_limit_bytes
        ):
            value["attachments"] = []
            value["text"].append(
                "成果附件合计超过邮件限制，未附文件，需管理员单独交付。"
            )
    return bundles
