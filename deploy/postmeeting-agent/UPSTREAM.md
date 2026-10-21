<!-- 2026-10-20，wyy 新增：会后任务官方 dsh 的来源、版本及 API 调用位置记录。 -->
# DeepSeek Harness 来源

- 官方源码：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)
- 固定 SDK/runtime：[deepseek-harness-sdk 0.2.1rc2](https://pypi.org/project/deepseek-harness-sdk/0.2.1rc2/)，属于预览版本。
- `Dockerfile.runner` 安装 SDK 及配套原生 runtime；代码留在任务镜像的 Python site-packages，不在服务器另复制一份上游源码。
- `runner.py` 创建 `DeepSeekHarness(provider='deepseek-official', model='deepseek-flash', profile='sdk-minimal')` 并执行 `harness.run(...)`，SDK 完成实际 API 调用。
- 禁用 `session-log-deepseek` 上传；模型推理仍会把当前会议材料发送至所配置的 DeepSeek API。
- 不修改上游 SDK。更换版本需重新验证 API、工具和日志行为。
