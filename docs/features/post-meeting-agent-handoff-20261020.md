<!-- 2026-10-20，wyy 新增：会后按用户执行任务功能的公司审核交接入口，记录默认关闭、部署恢复、变更清单和验证边界。 -->
# 会后任务功能审核交接

日期：2026-10-20；新增及整理人：wyy。

## 最终状态

新增功能第一版源码保留在服务器C `/data/meet-main`，供公司审核；未commit、未push。基线为GitHub `Damon-Loong/meet` main分支，核查HEAD为 `11b93ff5562ddd57c046371a65e5ef9ed17a9956`。原有3个文件修改，新增业务模块、可选部署配方及文档。公司应审核差异后按自身分支流程提交合并，不能把当前工作区直接视为已合并版本。

用户要求结束试用，现已恢复试用前的线上部署：

- 摘要服务仅由原 `/data/meet-deploy/compose.yaml` 启动，镜像为 `lasuite-meet/summary:transcript-first-20261020`，镜像ID `sha256:48a3a07a03e063ec74abdcf787bbd14fffea0eae70a37d7f5d815d5a59cf9538`，Celery响应正常。
- 摘要容器已重建，因此容器ID和启动时间发生变化；镜像、基础配置及挂载恢复原服务定义，不加载新功能环境配置和状态挂载。
- 新增postmeeting worker已停止并移除，闲置独立出站网络已移除；运行容器恢复16个，其余15个原有容器ID、镜像和启动时间与试用前一致。
- 源码、无密钥模板及实际postmeeting-common配置均默认关闭；实际试用白名单清空。原compose文件和其他13份环境配置未修改。
- 用户已经清空实际API配置，经检查确认；所有剩余运行或停止的容器均未保留非空DEEPSEEK_API_KEY。此前持有启动时密钥的worker容器已移除。未在模型平台操作或核实密钥撤销。
- 线上outbox无已接管未完成任务。独立历史失败/作废样例中的delivering状态保留为测试证据，不等同于生产待执行任务；没有对应worker在执行，禁止自动重放这些历史状态。

保留源码、配置空模板、未运行的构建镜像和受限测试记录，以便审核及复现。这里的“恢复部署”指运行服务回到原镜像与原配置，不是删除所有新增代码、镜像或日志。

## 审核文件入口

| 路径 | 作用及审核重点 |
|---|---|
| src/summary/summary/core/config.py | 新配置及默认false；不填密钥 |
| src/summary/summary/core/celery_worker.py | 正常纪要/补发后的可选交接，保留原转录和邮件行为 |
| src/summary/summary/core/email_service.py | 每人任务文字和已验证附件，原调用默认不变 |
| src/summary/summary/core/postmeeting_tasks.py | 独立worker、持久化交接、幂等及个人邮件账本 |
| src/summary/summary/core/postmeeting_processing.py | 姓名/邮箱归属、任务识别、逐任务执行及结果分配 |
| src/summary/summary/core/postmeeting_prompts.py | 新增提取/执行提示词，不修改原纪要提示词 |
| src/summary/summary/core/agent_runner.py | 官方DeepSeek Harness隔离任务容器、检查点与超时 |
| src/summary/summary/core/artifact_validation.py | 附件类型、路径、大小及Office基础结构检查 |
| deploy/postmeeting-agent | 版本化镜像配方、SDK入口、默认关闭配置模板及验收入口 |
| docs/features/post-meeting-agent.md | 完整设计、文件结构、状态和限制 |
| docs/features/post-meeting-agent-test-20261020.md | 初轮合成Excel/PPT、缺数据与邮件验收，保留失败和PPT受控补跑记录 |
| docs/features/post-meeting-agent-three-checks-20261020.md | 用户指定三项各一案例的无人干预检查、模拟转录与证据 |

部署配方属于main仓库的deploy目录，不是线上 `/data/meet-deploy` 目录。线上目录只存必要实际配置、状态及受限审计资料。真实邮箱、密钥及完整运行日志不提交Git。

## 已完成验证与边界

17项离线检查通过；真实deepseek-flash及官方Harness调用完成过合成文件任务，用户确认初轮测试邮件和Office附件可打开。初轮PPT包含一次受控补跑，不能声称首次全部自动成功。

后续用户指定的三例全部通过：讨论取消时零任务；双用户分别收到11+13=24与101+103=204的本人Excel；单任务7+8=15自动生成并邮件交付。三例由正式worker循环自动执行，没有人工补跑或发信放行。发送后独立读取Excel、重新计算公式通过；共4封邮件获SMTP接受。该轮收件箱实际到达尚未获得用户确认。

未完整验证真实网页录音到邮件全链路、全部异常恢复、复杂归属、恶意输入或并发可靠性。单例通过不是生产可靠性或科研收益结论。附件结构校验也不替代业务事实正确性检查。

## 公司审核通过后的配置及部署

实际API填写位置：`/data/meet-deploy/env.d/postmeeting-agent` 的 `DEEPSEEK_API_KEY=`，当前为空。官方SDK所用基址为 `https://api.deepseek.com/anthropic`。模型为deepseek-flash，SDK版本 `deepseek-harness-sdk==0.2.1rc2`。密钥仅交给可信worker，不能写入源码或给摘要服务。

开关位于 `/data/meet-deploy/env.d/postmeeting-common` 的 `POSTMEETING_AGENT_ENABLED=false`。白名单为 `POSTMEETING_ALLOWED_RECIPIENT_EMAILS=[]`；空数组在开启后代表不限制收件人，公司小范围试用应先显式配置允许的邮箱。仅启动profile或修改磁盘配置不会自动启用/更新已启动容器。

审核后按 [部署说明](../../deploy/postmeeting-agent/README.md) 重新准备镜像和独立网络，使用原项目名lasuite-meet、原项目目录，显式合并原compose和main中的可选覆盖。先启动worker确认心跳，再启用摘要接管。当前保持关闭，不要直接启动第二套原有服务，也不要仅因源码有改动就重新构建原线上服务。

可信worker持有Docker socket，属于高权限组件；审核时应核对职责边界、模型容器挂载、凭据流向、附件验证和状态恢复。模型执行容器不持有邮件凭据及Docker socket。

关闭及回滚应先停止新接管、核对已有任务，再停止worker并恢复基础compose。不能清空账本、重置sending/uncertain状态后盲目重发。实际文件权限、数据保留周期及之后的上线范围由公司确定。

## 可交付审查包

受限目录 `/data/meet-deploy/postmeeting-agent/review-20261020` 保存最终源码补丁 `postmeeting-agent.patch`、文件哈希及状态说明 `manifest.json`。补丁基于上面的HEAD，包含三个已有文件的差异和全部新增文件，不包含实际配置、邮箱或密钥。补丁仅供审查，不代表已提交Git；应用前需核对公司仓库基线。


## 2026-10-21 GitHub 提交说明（wyy）

用户已明确授权将本功能直接提交至GitHub仓库main分支。本记录前文“未commit、未push”描述的是2026-10-20交接时点；2026-10-21提交操作结果及最终版本以仓库Git历史为准。此次仅发布源码、无密钥模板和文档，不重新部署，不启用新功能。

开关实际位置仍为服务器C `/data/meet-deploy/env.d/postmeeting-common` 中的 `POSTMEETING_AGENT_ENABLED=false`；API密钥填写位置为 `/data/meet-deploy/env.d/postmeeting-agent` 中的 `DEEPSEEK_API_KEY=`，当前为空。两个实际配置文件不进入仓库；仓库模板位于 `deploy/postmeeting-agent/common.env.example` 与 `agent.env.example`。填写或改开关后仍须按部署说明应用配置，当前基础部署不会自动加载可选覆盖。
