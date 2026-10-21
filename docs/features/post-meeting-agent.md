<!-- 2026-10-20，wyy 新增：记录“会后纪要驱动 Agent 按用户执行并通过邮件交付成果”功能的设计、文件职责、边界与恢复方式。 -->
# 会后纪要驱动 Agent 任务执行与个人邮件交付

> **最终状态（2026-10-20，wyy）：试用已结束，新功能关闭。** 已恢复试用前摘要镜像及基础部署，新增worker已移除，API配置为空，运行容器恢复16个。前文/下文涉及启用状态的描述仅记录当时试用情况。当前审核入口见 [审核交接](post-meeting-agent-handoff-20261020.md)。


新增日期：2026-10-20。新增者：wyy。

## 1. 原始需求与本次范围

会议结束后复用已有自动总结，识别会议明确要求执行的工作，例如汇总已有数据为 Excel、制作进展汇报 PPT。能够完成时生成真实文件和文字说明；不能完成时明确说明缺少什么、为何不能完成。最终按每个用户交付会议资料和属于该用户的任务结果。

第一版采用官方 DeepSeek Harness SDK `0.2.1rc2` 和模型标识 `deepseek-flash`。保守执行，仅支持文字、xlsx、pptx；附件可包含相应 PDF 预览及文本材料。不接入企业数据库、云盘、外部资料搜索和其他 Agent，不自动联系人或执行线下动作。

本功能也可用于后续研究“会议证据能否可靠触发正确的任务执行”：应分别评价任务识别、归属、材料充分性、产物正确性与交付，而不能把文件生成等同于业务任务完成。本次只完成用户明确授权的工程原型，未运行研究实验，不宣称实证收益。

## 2. 代码基线和目录安排

服务器：afb-c。唯一修改的远端目录：`/data/meet-main`。
基线为 GitHub `Damon-Loong/meet` main 的 `11b93ff5562ddd57c046371a65e5ef9ed17a9956`，开发开始前该目录工作区干净。此前已回退的旧实现不再直接恢复。本实现建立在同步后的源码上，不覆盖线上旧镜像内的文件。

遵循仓库现有 `src/`、`deploy/`、`docs/` 分工：

```text
meet-main/
  src/summary/summary/core/
    config.py                    # 修改：默认关闭的开关和资源上限
    celery_worker.py             # 修改：普通纪要、补发纪要的可选接管点
    email_service.py             # 修改：保留旧接口，增加单人结果及验证附件
    postmeeting_prompts.py       # 新增：独立的提取、执行提示词
    postmeeting_processing.py    # 新增：任务证据、归属和按人汇总
    postmeeting_tasks.py         # 新增：持久化 outbox、独立 worker、个人交付
    agent_runner.py              # 新增：任务容器、时限及阶段检查点
    artifact_validation.py       # 新增：产物路径、格式和结构检查
  deploy/postmeeting-agent/
    Dockerfile.runner            # 新增：官方 dsh、Office 生成和检查工具
    Dockerfile.worker            # 新增：同份 summary 源码加 Docker 客户端
    runner.py                    # 新增：SDK 实例化和实际模型调用入口
    compose.override.yaml        # 新增：显式选择的部署覆盖，不自动加载
    common.env.example           # 新增：默认 false 的非敏感配置模板
    agent.env.example            # 新增：空 API 密钥模板
    prepare.sh                   # 新增：构建镜像、创建执行网络，不启动服务
    .dockerignore                # 新增：限制构建上下文
    UPSTREAM.md                  # 新增：官方 dsh 来源与版本
    README.md                    # 新增：后续部署、填写密钥和回滚说明
  docs/features/post-meeting-agent.md  # 新增：本记录
```

所有新增自有文件开头均注明日期、wyy 和在原始需求中的职责。没有改动原有摘要提示词、模型服务、分段提取逻辑、摘要审阅、文档格式化、delivery_state.py 和原始 Dockerfile。新 worker/runner 镜像仅在后续手动构建时产生；本轮服务器没有另建上游 dsh 工作副本。

服务器 `/data/meet-deploy` 与上述仓库里的 `deploy/` 不是同一目录。首次源码交付未修改 meet-deploy；2026-10-20 按用户填写 API 的需要，补齐 env.d/postmeeting-agent 和 env.d/postmeeting-common 两个必要配置文件，未修改其他部署配置。以后 meet-deploy 只需保留真实环境配置和运行状态，不复制业务 Python 源码或整份 dsh。

## 3. 完整处理流程

1. 现有摘要任务按原提示词、原模型生成并保存纪要。关闭开关时不导入新调度模块，不创建执行状态、不调用 dsh，沿用现有邮件路径。
2. 开关开启、邮件启用、有收件人和标题、有可用纪要且独立 worker 心跳正常时，将本次纪要、转录、参会者和后端确定的收件地址持久化到独立 outbox。接管成功后原群发邮件路径停止，由 worker 按人发送完整资料。
3. 只有转录、纪要暂不可用时，不进入 Agent，原有先发转录、延迟补发纪要逻辑保持。补发成功时也支持接入新功能，先前转录邮件不重复发送。
4. 依据后端参会者名单和收件邮箱精确对应姓名，为模型分配匿名用户 ID。多账号同名、姓名冲突、不能唯一对应时不自动归属。邮箱由程序决定，模型不能添加收件人。
5. 提取阶段把已有纪要、原始转录及候选 ID/姓名交给独立 dsh 容器，最多提取 12 项明确未来任务。要求逐字原文证据；模型给出的引文必须真实出现在转录中，且必须包含所分配人员的唯一登记姓名，否则进入待确认。
6. 每项通过检查的任务单独启动 dsh 容器。模型依据材料和已安装工具判断能否完成，并实际生成交付物。有明确多个责任人的同一任务仅执行一次，把结果交给这些责任人。第一版身份门槛偏严格，“我来做”等无法从引文确认姓名的承诺可能暂不执行。
7. 程序检查状态、字段和产物；缺少信息或存在未完成要求的 completed 降为 partial。xlsx/pptx 没有真实对应文件不能通过 completed 检查。失败时丢弃该任务未通过验证的附件，给出未完成说明。
8. 每位用户分别收到邮件：原有转录与纪要附件、原有录制文件链接、`会后任务结果.txt`，以及属于自己的成果文件。没有可执行任务、材料不足、执行失败也发送原会议资料和诚实说明。归属尚未确认的会议任务作为待确认说明，不附上他人已完成任务的成果。
9. 每封邮件复用现有 DeliveryState 的 sending/sent/uncertain 检查。全部个人邮件确认成功后，原群发阶段标记为 sent，并按原机制排队导入已交付纪要的个人记忆。

## 4. 提示词与程序检查的分工

新增提示词在 `postmeeting_prompts.py`，原有 `prompt.py` 保持不动。

提取提示词关注：只提取会议明确要求或接受的未来任务，排除建议、已完成事项、纯线下动作；不得猜责任人；输出 description、owner_ids、原文 quote、deliverable、requirements、ambiguity。没有任务返回空列表。

执行提示词关注：先判断必要资料是否充分；只使用本次会议材料和已有本地工具；允许使用原话里已有的数据；不能编造业务数字和进展。缺材料时列明缺项和用途；允许有用模板，但须显著标注草稿、待补数据并设为 partial。Excel 要求生成真实文件并重新打开；PPT 要求用 LibreOffice 生成 PDF 预览、检查页数和内容。最终输出 completed/partial/blocked_missing_data/needs_confirmation/failed 和 result_text、artifacts、missing_information、unresolved_requirements、checks_performed。

“这些材料是否足以完成业务任务”需要 LLM 参与判断。程序负责客观约束：名单、邮箱、引文存在、输出 schema、文件存在、路径、大小、格式、资源上限和交付状态；不依赖 LLM 来决定能否越权访问路径或更改收件人。模型自报检查不是独立业务正确性证据。

## 5. dsh、API 和运行边界

业务适配代码 `agent_runner.py` 通过 Docker CLI 启动一次性 runner；`runner.py` 实例化官方 SDK 并执行 `harness.run`；实际 HTTP 请求由 SDK 的 DeepSeek 适配器完成。`Dockerfile.runner` 固定安装 SDK/runtime。模型标识固定 deepseek-flash，API 地址默认 `https://api.deepseek.com`。

后续 API 配置模板：`/data/meet-main/deploy/postmeeting-agent/agent.env.example`。
后续实际凭据文件：`/data/meet-deploy/env.d/postmeeting-agent`，填写 `DEEPSEEK_API_KEY=`，权限 600。2026-10-20 补充：已创建该文件，密钥留空；同时创建默认关闭的 postmeeting-common，两者均未被运行服务加载。非敏感开关配置模板为 common.env.example，未来实际路径是 `/data/meet-deploy/env.d/postmeeting-common`。

可信 worker 可访问 SMTP 配置、现有投递账本和 Docker socket；持有 socket 等价于高权限，不能把此组件视为普通无权限沙箱。只有它启动模型容器。模型容器没有 socket、SMTP 配置、业务数据库或其他用户工作区挂载，只有单次输入只读目录、单次输出可写目录和临时目录；使用非 root UID、只读根目录、去 capabilities、限制进程、内存与 CPU。

模型容器获得本次推理所需的 DeepSeek API 凭据。独立出站网络用于隔离 Compose 内网，但不是严格域名白名单，提示词也不是网络隔离机制。禁用 SDK 默认的 session-log 上传；正常模型推理仍向 API 服务商提交本次会议材料。部署前应由公司确认数据使用范围。

默认单阶段硬超时 300 秒、整批启动预算 900 秒、单请求 max_tokens 8192。整批预算会阻止超预算后继续启动任务，控制器清理可能另有少量开销；SDK 可能有多次工具推理及自动压缩，max_tokens 是每次请求输出上限，不是整批 token/费用上限。容器内硬超时也在控制器异常退出后生效。

转录大于 300000 字符时不调用模型。每次产物最多 10 个，允许 xlsx、pptx、pdf、txt、md、csv；每人汇总附件默认上限 18 MiB，超限不附文件并提示人工交付。Office 压缩包限制文件数和解压总量，拒绝宏、二进制嵌入和外部关系。普通邮件原有转录、纪要及 MIME 编码另有开销，不保证所有邮件服务器都接受其总大小；实际 SMTP 限制需后续测试。

任务容器禁用 Docker 日志持久化，控制器也不打印原始模型 stderr；返回的非敏感错误类别写入执行说明。单文件写入硬上限 64 MiB，但这不是整个输出目录的磁盘配额；大规模试用前需为状态盘设置容量、配额和清理策略。

结构检查只能证明文件具有基本可读结构，不能证明公式、数据、排版或会议事实正确。提示词要求模型复读和预览，但本轮未运行文件生成，也未建立独立语义验收器。事实与视觉正确性须后续样本核验。

## 6. 持久化、幂等与异常处理

运行状态未来保存在 `/data/meet-deploy/postmeeting-agent/state`，通过相同 bind mount 映射至摘要进程和可信 worker 的 `/var/lib/postmeeting`，不进入 Git。

- outbox.sqlite3：会议任务、原邮件阶段交接、每人交付状态与结果快照。
- worker-heartbeat、worker.lock：存活检查与单 worker 互斥。
- workspaces/<阶段哈希>/input、output：每次模型调用独立材料和产物。
- results/<阶段哈希>.json：控制器写入的阶段检查点，模型容器看不到、不允许修改。
- 旧 meet-memory/state 中的 delivery.sqlite3：继续记录每封实际邮件的发送状态。

相同租户、录制源、转录、纪要、收件人集合及流水线版本共用一个 job；不同纪要内容可能产生新 job，因此不是跨所有摘要版本的严格“一次会议永远只执行一次”。阶段成功结果可复用；进程在执行中断后不会盲目重跑，改发中断说明。一个 worker 用文件锁串行处理。

接管前发现 worker 无心跳时直接走原邮件路径。接管持久化后使用粘性交接，后续重试不因 worker 暂时掉线重新群发。原账本保留 postmeeting 状态，阻止旧发送器在中途关闭开关后重复发送。outbox 和原账本是两个数据库，接管之间有小窗口；worker 等待原阶段成功预留，未完成或冲突进入人工核查。

SMTP 超时或断线有可能服务端已接收，因此不自动重发。发送失败、无法判断是否成功、进程异常等进入 needs_review，保留状态供管理员核查。原会议资料也会受实际邮件服务故障影响，本实现不承诺“所有异常均必达”。禁止清空账本后重跑。

当前未提供管理 UI、自动重试 needs_review、历史任务批量补跑、成果下载网站或长期存储清理作业。持久化含会议正文与用户邮箱，目录应限制访问，并由公司制定保留和清理周期；本轮不增加长期值守任务。

## 7. 启用、关闭与回滚

具体步骤见 deploy/postmeeting-agent/README.md。需要先审核源码、从本目录配方构建镜像、准备外部配置和状态目录，然后在隔离环境验收。上线必须显式选择 compose.override.yaml；当前线上 compose 不会自动加载它。

仅启动 profile 不代表启用，还须双方进程加载 `POSTMEETING_AGENT_ENABLED=true`。仅改环境文件不会改变已启动容器，须在后续部署阶段应用配置。启用顺序先 worker 心跳、再摘要侧交接；生产未启用前一直保持 false。

启用后回滚先停止新任务接入、保留并核对已有任务，排空或人工处理 pending/needs_review，再停止 worker，恢复原镜像和配置。不能简单删目录、重置交付状态或把已接管任务重新群发。若要彻底撤回源码，可据代码审查差异和本地基线备份恢复这三个修改文件，并移除清单中的新增文件；不得覆盖公司之后的独立修改。

## 8. 本轮验证与尚未验证的内容

按用户要求仅进行源码静态检查，不构建镜像、不启动新服务、不调用模型 API、不发测试邮件、不 git commit/push。9 个 Python 文件通过语法解析及未定义名称等基础检查；5 个新增业务模块通过仓库 Ruff 规则；部署 YAML 可解析、所有新增文件都有职责注释，代码及配置模板的开关均为 false。现有文件保留原有风格，本轮不清理全仓历史 lint 问题。远端最终差异和运行容器核对结果保存在本地交付核查记录。

后续必要验收：开关关闭时邮件与纪要回归；无任务、明确文字任务、可用数据 Excel/PPT、材料不足、同名与未知责任人、任务共享、模型非法 JSON、超时、非法文件、超大附件；重复回调、worker 中断与恢复、SMTP 明确失败及不确定结果；补发纪要与个人记忆保持一致。先模拟外部调用，再进行小规模真实 API 和测试邮箱验证；真实测试不得把演示结果写成生产可靠性或研究收益结论。

目前只提供可审查实现和后续部署入口，SDK 实际启动、模型 deepseek-flash 的账号可用性、费用、文件排版、邮件附件兼容性均需下一阶段验证。


## 2026-10-20 测试与试用状态更新（wyy）

前文“未调用 API、未部署”等状态记录首次源码交付时点。后续已完成真实 API、合成 Excel/PPT、邮件交付及用户附件打开确认；目前仅对已授权测试邮箱启用，源码默认仍为 false。PPT 验收包含一次明确控制的补跑，真实网页录制全链路仍待验证。当前 API 基址为 `https://api.deepseek.com/anthropic`。

完整证据、已知限制、文件入口与回滚说明见 [测试与试用记录](post-meeting-agent-test-20261020.md)。
