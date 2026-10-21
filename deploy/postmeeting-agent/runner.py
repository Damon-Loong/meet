"""2026-10-20，wyy 新增：会后任务容器内的官方 dsh SDK/API 入口。

装配独立提示词和当次会议材料，禁用 session-log 上传，返回结构化结果。
整个容器设硬超时；实际 DeepSeek API 调用由固定版本官方 SDK 执行。
"""

import contextlib
import json
import os
from pathlib import Path
import sys
import threading


def main():
    """Execute one isolated stage; container lifetime also bounds SDK child processes."""
    timeout = max(1, int(os.environ.get("RUN_TIMEOUT", "300")))
    # PID 1 exits on timeout even if its controller is killed or the native SDK hangs.
    watchdog = threading.Timer(timeout, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        from deepseek_harness import DeepSeekHarness

        request = json.loads(Path("/input/request.json").read_text(encoding="utf-8"))
        prompt = (
            request["instruction"]
            + "\n\n本次任务材料：\n"
            + json.dumps(request["context"], ensure_ascii=False)
        )
        home = Path("/tmp/dsh-home")
        home.mkdir(mode=0o700)
        patch = Path("/tmp/privacy.patch.yml")
        patch.write_text(
            "- id: session-log-deepseek\n  config:\n    enabled: false\n",
            encoding="utf-8",
        )
        os.environ["HOME"] = "/tmp"
        os.environ["DSH_SYSTEM_PROMPT"] = (
            "你是受限的会议任务执行助手。严格遵循输入 instruction；"
            "如 context.task 存在，它是唯一授权任务，其他会议待办只是参考材料。"
            "最终回复必须是 instruction 要求的单个合法 JSON 对象，"
            "不得输出 Markdown 围栏、前言、结语或 JSON 以外的说明。"
        )
        with contextlib.redirect_stdout(sys.stderr):
            with DeepSeekHarness(
                provider="deepseek-official",
                model="deepseek-flash",
                max_tokens=int(os.environ.get("DSH_MAX_TOKENS", "8192")),
                cwd="/output",
                dsh_home=str(home),
                profile="sdk-minimal",
                patches=(str(patch),),
                request_timeout_seconds=timeout,
            ) as harness:
                result = harness.run(prompt, session_id="postmeeting")
        error_code = None
        for event in reversed(result.events):
            if isinstance(event, dict) and event.get("type") == "turn/end":
                reason = event.get("data", {}).get("reason", {})
                code = reason.get("error", {}).get("code")
                if (
                    isinstance(code, str)
                    and code.isascii()
                    and len(code) <= 40
                    and code.replace("_", "").isalnum()
                ):
                    error_code = code
                break
        print(
            json.dumps(
                {
                    "finish_reason": result.finish_reason,
                    "final_response": result.final_response,
                    "error_code": error_code,
                },
                ensure_ascii=False,
            )
        )
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    main()
