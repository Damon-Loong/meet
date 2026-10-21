"""2026-10-20，wyy 新增：会后任务的离线回归检查，不调用 API 或发送邮件。

覆盖关闭开关、试用范围、交接中断、归属证据、诚实状态和不安全附件。
运行环境需要能导入 main 的 summary 包；使用标准库 unittest 和模拟调用。
"""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from summary.core.artifact_validation import validate_artifacts
from summary.core.delivery_state import DeliveryState
from summary.core.postmeeting_processing import candidates, process
from summary.core.postmeeting_tasks import database, enqueue


class PostmeetingChecks(unittest.TestCase):
    """Verify important execution and delivery decisions without external actions."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = SimpleNamespace(
            postmeeting_agent_enabled=True,
            email_delivery_enabled=True,
            postmeeting_state_dir=str(self.root / "state"),
            meeting_memory_state_file=str(self.root / "memory" / "state.sqlite3"),
            postmeeting_allowed_recipient_emails=["alice@example.com"],
            postmeeting_batch_timeout_seconds=90,
            postmeeting_task_timeout_seconds=30,
            postmeeting_attachment_limit_bytes=1024 * 1024,
        )
        self.data = {
            "tenant_id": "offline-test",
            "content": "张三：请张三汇总这两个数字：10 和 20。",
            "recipient_emails": ["alice@example.com"],
            "media_recording_id": None,
            "push_to_docs_config": {"title": "合成数据离线验收"},
            "participants": [{"name": "张三", "email": "alice@example.com"}],
        }
        self.payload = SimpleNamespace(model_dump=lambda **_kw: self.data)

    def heartbeat(self):
        root = Path(self.settings.postmeeting_state_dir)
        root.mkdir()
        (root / "worker-heartbeat").touch()

    def processing_data(self):
        return {
            "recipients": self.data["recipient_emails"],
            "participants": self.data["participants"],
            "transcript": self.data["content"],
            "summary": "合计任务",
        }

    def task(self, **changes):
        task = {
            "description": "汇总两个数字",
            "owner_ids": ["u0"],
            "quote": self.data["content"],
            "deliverable": "text",
            "ambiguity": "",
        }
        return {**task, **changes}

    def result(self, **changes):
        result = {
            "status": "completed",
            "result_text": "合计 30。",
            "artifacts": [],
            "_output_dir": str(self.root),
            "missing_information": [],
            "unresolved_requirements": [],
            "checks_performed": ["核对 10+20=30"],
        }
        return {**result, **changes}

    def test_disabled_has_no_state_side_effect(self):
        self.settings.postmeeting_agent_enabled = False
        self.assertFalse(enqueue(self.settings, self.payload, "纪要", "stage"))
        self.assertFalse((self.root / "state").exists())

    def test_no_worker_keeps_original_route(self):
        self.assertFalse(enqueue(self.settings, self.payload, "纪要", "stage"))
        self.assertFalse((self.root / "state").exists())

    def test_mixed_recipients_are_outside_pilot(self):
        self.heartbeat()
        self.data["recipient_emails"].append("other@example.com")
        self.assertFalse(enqueue(self.settings, self.payload, "纪要", "stage"))
        self.assertFalse((self.root / "state" / "outbox.sqlite3").exists())

    def test_repeat_handoff_is_sticky_after_worker_outage(self):
        self.heartbeat()
        self.assertTrue(enqueue(self.settings, self.payload, "纪要", "stage"))
        (self.root / "state" / "worker-heartbeat").unlink()
        self.assertTrue(enqueue(self.settings, self.payload, "纪要", "stage"))
        with database(self.settings) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        self.assertEqual(
            DeliveryState(self.settings.meeting_memory_state_file).status("stage"),
            "postmeeting",
        )

    def test_retry_repairs_interrupted_stage_reservation(self):
        self.heartbeat()
        enqueue(self.settings, self.payload, "纪要", "stage")
        mail = DeliveryState(self.settings.meeting_memory_state_file)
        # Equivalent to a crash after outbox commit, before old-stage reservation.
        mail.finish("stage", "ready")
        self.assertTrue(enqueue(self.settings, self.payload, "纪要", "stage"))
        self.assertEqual(mail.status("stage"), "postmeeting")

    def test_retry_resumes_only_unexecuted_handoff_wait(self):
        self.heartbeat()
        enqueue(self.settings, self.payload, "纪要", "stage")
        mail = DeliveryState(self.settings.meeting_memory_state_file)
        mail.finish("stage", "ready")
        with database(self.settings) as db:
            db.execute("UPDATE jobs SET status='handoff_wait'")
        self.assertTrue(enqueue(self.settings, self.payload, "纪要", "stage"))
        with database(self.settings) as db:
            self.assertEqual(
                db.execute("SELECT status FROM jobs").fetchone()[0], "pending"
            )
        self.assertEqual(mail.status("stage"), "postmeeting")

    def test_duplicate_display_names_do_not_assign(self):
        data = {
            "recipients": ["alice@example.com", "bob@example.com"],
            "participants": [
                {"name": "张三", "email": "alice@example.com"},
                {"name": "张三", "email": "bob@example.com"},
            ],
        }
        self.assertEqual([p["name"] for p in candidates(data)], ["", ""])

    def test_invented_quote_never_executes(self):
        with patch(
            "summary.core.postmeeting_processing.run_agent",
            return_value={"tasks": [self.task(quote="张三：这是不存在的原话。")]},
        ) as call:
            result = process(self.settings, "test", self.processing_data())
        self.assertEqual(call.call_count, 1)
        self.assertIn("未执行", "\n".join(result["u0"]["text"]))

    def test_missing_data_downgrades_completed(self):
        with patch(
            "summary.core.postmeeting_processing.run_agent",
            side_effect=[
                {"tasks": [self.task()]},
                self.result(missing_information=["缺少本周真实进度"]),
            ],
        ):
            result = process(self.settings, "test", self.processing_data())
        self.assertIn("部分完成", "\n".join(result["u0"]["text"]))

    def test_results_are_recipient_specific(self):
        data = self.processing_data()
        data["recipients"].append("bob@example.com")
        data["participants"].append({"name": "李四", "email": "bob@example.com"})
        with patch(
            "summary.core.postmeeting_processing.run_agent",
            side_effect=[{"tasks": [self.task()]}, self.result()],
        ):
            result = process(self.settings, "test", data)
        self.assertIn("合计 30", "\n".join(result["u0"]["text"]))
        self.assertNotIn("合计 30", "\n".join(result["u1"]["text"]))

    def test_execution_failure_retains_honest_report(self):
        with patch(
            "summary.core.postmeeting_processing.run_agent",
            side_effect=[{"tasks": [self.task()]}, RuntimeError("simulated timeout")],
        ):
            result = process(self.settings, "test", self.processing_data())
        self.assertIn("未完成", "\n".join(result["u0"]["text"]))
        self.assertEqual(result["u0"]["attachments"], [])

    def test_unassigned_document_type_is_not_delivered(self):
        p = self.root / "unexpected.pptx"
        with zipfile.ZipFile(p, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("ppt/presentation.xml", "<presentation/>")
            archive.writestr("ppt/slides/slide1.xml", "<slide/>")
        with patch(
            "summary.core.postmeeting_processing.run_agent",
            side_effect=[
                {"tasks": [self.task(deliverable="xlsx")]},
                self.result(status="partial", artifacts=[{"path": "unexpected.pptx"}]),
            ],
        ):
            result = process(self.settings, "test", self.processing_data())
        self.assertEqual(result["u0"]["attachments"], [])
        self.assertIn("未完成", "\n".join(result["u0"]["text"]))

    def test_artifact_parent_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_artifacts(self.root, [{"path": "../outside.txt"}])

    def test_office_external_relationship_is_rejected(self):
        p = self.root / "bad.xlsx"
        with zipfile.ZipFile(p, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
            archive.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                "<Relationships><Relationship TargetMode = 'External' Target='https://example.com'/></Relationships>",
            )
        with self.assertRaises(ValueError):
            validate_artifacts(self.root, [{"path": "bad.xlsx"}])

    def test_normal_ppt_printer_settings_are_accepted(self):
        p = self.root / "normal.pptx"
        with zipfile.ZipFile(p, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types><Default Extension="bin" ContentType="application/vnd.openxmlformats-officedocument.presentationml.printerSettings"/></Types>',
            )
            archive.writestr("ppt/presentation.xml", "<presentation/>")
            archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            archive.writestr(
                "ppt/printerSettings/printerSettings1.bin", b"test devmode"
            )
        self.assertEqual(
            len(validate_artifacts(self.root, [{"path": "normal.pptx"}])), 1
        )

    def test_embedded_office_binary_is_rejected(self):
        p = self.root / "unsafe.pptx"
        with zipfile.ZipFile(p, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("ppt/presentation.xml", "<presentation/>")
            archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            archive.writestr("ppt/embeddings/oleObject1.bin", b"not allowed")
        with self.assertRaises(ValueError):
            validate_artifacts(self.root, [{"path": "unsafe.pptx"}])

    def test_text_artifact_is_accepted(self):
        (self.root / "result.txt").write_text("合成数据测试", encoding="utf-8")
        accepted = validate_artifacts(self.root, [{"path": "result.txt"}])
        self.assertEqual(accepted[0]["mime"], "text/plain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
