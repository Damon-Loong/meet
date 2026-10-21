<!-- 2026-10-20，wyy 新增：会后按用户自动执行任务的部署入口与配置说明。 -->
# 会后任务部署配方

> **最终状态（2026-10-20，wyy）：试用已结束，新功能关闭。** 已恢复试用前摘要镜像及基础部署，新增worker已移除，API配置为空，运行容器恢复16个。前文/下文涉及启用状态的描述仅记录当时试用情况。当前审核入口见 [审核交接](../../docs/features/post-meeting-agent-handoff-20261020.md)。


完整设计、文件清单、失败处理和验收步骤见 [功能记录](../../docs/features/post-meeting-agent.md)。
此目录属于 `/data/meet-main` Git 仓库，和已有 `deploy/paas` 并列；不是服务器的 `/data/meet-deploy`。
业务代码在 `src/summary/summary/core`，这里仅保存镜像配方、SDK 入口、可选覆盖配置和无密钥模板。

## 当前交付状态

源码和模板默认 `false`。已完成合成API/文件/邮件及三项指定检查；试用结束后已关闭功能、清空API并恢复原部署。审核细节和证据边界见下方交接入口。
不要运行历史恢复目录中的旧 overlay 恢复脚本。本实现使用同步后的 main 源码正常构建。

## 后续填写 API 的位置

模板：`/data/meet-main/deploy/postmeeting-agent/agent.env.example`。
实际运行配置：`/data/meet-deploy/env.d/postmeeting-agent`，在其中填写 `DEEPSEEK_API_KEY=`。
2026-10-20 补充：已在 meet-deploy 创建空密钥配置及默认关闭的 common 配置，供用户填写；尚未加载到任何运行服务。
密钥文件仅由可信 worker 加载，不给摘要 Celery 服务；任务容器只取得模型 API 凭据。

## 公司审核通过后的部署步骤

1. 公司审核当前 main 改动；保留当前运行镜像和配置用于回滚。
2. 实际配置已按模板建立在 meet-deploy 的 `env.d/postmeeting-common`、`env.d/postmeeting-agent`，权限 600。填写后者的 API 密钥，保持前者开关 false；其他环境迁移时才需复制模板，不要覆盖已填写的密钥。
3. 创建 `/data/meet-deploy/postmeeting-agent/state`，权限 700。确认它没有指向业务源码或其他数据目录的符号链接。
4. 手动运行本目录 `prepare.sh`，从 main 构建 summary、可信 worker、官方 dsh runner 三个镜像，并创建独立出站网络。此步骤不启动服务，但会下载依赖、创建镜像和网络。
5. 使用与现有线上部署相同的项目名（当前为 `lasuite-meet`）及项目目录检查合并配置。命令输出可能包含现有环境变量，应仅在受控终端查看，不复制到共享日志。

```sh
docker compose --project-directory /data/meet-deploy -p lasuite-meet \
  -f /data/meet-deploy/compose.yaml \
  -f /data/meet-main/deploy/postmeeting-agent/compose.override.yaml \
  --profile postmeeting config --quiet
```

6. 先在隔离环境完成关闭开关回归、无 API 的异常路径、模型小样本、真实文件和个人邮件验收，再安排生产启用。不要仅运行以上覆盖文件，也不要启动不同项目名的第二套生产服务。
7. 计划启用时，在 common 配置设置 `POSTMEETING_AGENT_ENABLED=true`，先启动 postmeeting-worker，确认心跳，再只更新 summary-summarize；反向顺序会让未接管会议走原邮件路径。启动及更新命令应保留上面相同的 `-p`、项目目录和两个 `-f` 参数。

`POSTMEETING_HOST_STATE_DIR` 必须等于容器状态挂载所对应的宿主机绝对路径。若改 `MEET_DEPLOY_ROOT`，还须同步修改 common 配置里的宿主状态路径。

## 暂停与回滚

生产未启用时，保持开关 false 即可。启用后不能仅删除状态目录或只关闭摘要侧开关：已接管任务需要先排空，或者由管理员核对后停止 worker。`postmeeting` 状态表示旧群发流程已经让出交付权，禁止重置为 ready 后盲目群发。
SMTP 结果不确定、进程中断等任务进入 `needs_review`，不自动重发、不自动重新调用模型；请核对 outbox 和已有 delivery.sqlite3 再决定人工处理。
该可信 worker 持有 Docker socket，等价于高权限组件，必须限制镜像和配置修改者。模型容器没有 socket、SMTP 配置或业务数据库挂载；独立出站网络不是域名白名单。


## 2026-10-20 测试与试用状态更新（wyy）

前文“未调用 API、未部署”等状态记录首次源码交付时点。后续已完成真实 API、合成 Excel/PPT、邮件交付及用户附件打开确认；试用期间仅对已授权测试邮箱启用，现已关闭，源码默认仍为 false。PPT 验收包含一次明确控制的补跑，真实网页录制全链路仍待验证。当前 API 基址为 `https://api.deepseek.com/anthropic`。

完整证据、已知限制、文件入口与回滚说明见 [测试与试用记录](../../docs/features/post-meeting-agent-test-20261020.md)。
