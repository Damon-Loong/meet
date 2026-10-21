"""2026-10-20，wyy 新增：会后自动任务的 DeepSeek Harness 容器适配器.

在独立容器中提交提示词、收集结果。模型容器没有 Docker socket、SMTP、
业务数据库或其他用户工作区；仅可信调度 worker 可以启动任务容器。
"""

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path


def json_response(text):
    """Accept a JSON object, with an optional model-added Markdown fence."""
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected object response")
    return parsed


def _record_failure(checkpoint, reason, code=None):
    """Persist only bounded error categories, never SDK stderr or credentials."""
    path = checkpoint.with_suffix(".error.json")
    path.write_text(
        json.dumps({"finish_reason": reason, "error_code": code}), encoding="utf-8"
    )
    path.chmod(0o600)


def run_agent(settings, job_id, stage, instruction, context, timeout):  # noqa: PLR0913, PLR0917
    """Run one bounded container with fixed argv and private controller checkpoints."""
    key = hashlib.sha256((job_id + stage).encode()).hexdigest()
    # Controller-only checkpoints are outside the model-visible output mount.
    state = Path(settings.postmeeting_state_dir)
    checkpoint = state / "results" / (key + ".json")
    checkpoint.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if checkpoint.exists():
        return json.loads(checkpoint.read_text(encoding="utf-8"))
    folder = state / "workspaces" / key
    incoming, outgoing = folder / "input", folder / "output"
    incoming.mkdir(mode=0o755, parents=True, exist_ok=True)
    incoming.chmod(0o755)
    outgoing.mkdir(mode=0o700, exist_ok=True)
    # UID is dedicated to this one-shot container, never the host root user.
    if os.geteuid() == 0:
        os.chown(outgoing, 10001, 10001)
    request = incoming / "request.json"
    request.write_text(
        json.dumps(
            {"instruction": instruction, "context": context}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    request.chmod(0o644)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DeepSeek credential has not been configured")
    host_root = settings.postmeeting_host_state_dir.rstrip("/")
    host_folder = host_root + "/workspaces/" + key
    name = "meet-pm-" + uuid.uuid4().hex
    command = [
        "/usr/bin/docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--read-only",
        "--log-driver",
        "none",
        "--ulimit",
        "fsize=67108864:67108864",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--memory",
        "2g",
        "--cpus",
        "1",
        "--network",
        settings.postmeeting_runner_network,
        "--tmpfs",
        # dsh extracts native bindings into /tmp; Docker tmpfs defaults to noexec.
        "/tmp:rw,exec,nosuid,nodev,size=512m,mode=1777",  # noqa: S108
        "--mount",
        f"type=bind,src={host_folder}/input,dst=/input,readonly",
        "--mount",
        f"type=bind,src={host_folder}/output,dst=/output",
        "-e",
        "DEEPSEEK_API_KEY",
        "-e",
        "DEEPSEEK_BASE_URL",
        "-e",
        "DSH_MODEL=deepseek-flash",
        "-e",
        f"RUN_TIMEOUT={max(1, int(timeout))}",
        "-e",
        f"DSH_MAX_TOKENS={settings.postmeeting_max_output_tokens}",
        settings.postmeeting_runner_image,
    ]
    env = {
        **os.environ,
        "DEEPSEEK_BASE_URL": os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic"
        ),
    }
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv; no shell or model-supplied flags.
            command,
            input="",
            text=True,
            capture_output=True,
            timeout=timeout + 40,
            env=env,
            check=False,
        )
        if result.returncode:
            _record_failure(checkpoint, "container_exit", result.returncode)
            # Raw stderr can contain prompt, provider response or credentials.
            raise RuntimeError(
                "Harness container failed; verify SDK, credential and task limits"
            )
        envelope = json.loads(result.stdout)
        if envelope.get("finish_reason") != "completed":
            _record_failure(
                checkpoint, envelope.get("finish_reason"), envelope.get("error_code")
            )
            raise RuntimeError("Harness turn did not finish successfully")
        value = json_response(envelope["final_response"])
        value["_output_dir"] = str(outgoing)
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(checkpoint)
        return value
    finally:
        subprocess.run(  # noqa: S603 - fixed executable and internally generated name.
            ["/usr/bin/docker", "rm", "-f", name],
            capture_output=True,
            timeout=15,
            check=False,
        )
