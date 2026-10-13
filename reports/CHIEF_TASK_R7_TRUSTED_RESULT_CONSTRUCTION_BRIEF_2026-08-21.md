你是执行者，这是 R7 最后一项信任边界修正，也是唯一任务来源；中途没人可问，拿不准写 `BLOCKED.md` 后停。断线先读 `PROGRESS.md`，逐项更新。r7k8 已证明 Cursor 能认证、隔离执行并做单提交；失败仅因让模型自写验收 JSON。目标是让模型只干活，Control Plane 用 lease、Git 和 Chief 固定命令构造结果。冲突时：可信事实 > fail closed > 唯一 canary > 兼容旧自报。只有“只允许/不许”是硬边界。

## 我替领导拍的板

- 不再靠加强 prompt 让模型背 schema；模型最终文字不是身份、commit 或验收依据。
- Cursor CLI 外层 envelope 仍必须是唯一、合法、成功的 result；其内层文字只作不可信信息，丢弃且不进日志/报告。
- r7k8 已消耗 1 次且终止；全新 r7k9 最多再运行 `--print=1`。

## 界限

保留现有 8 个 file-store 候选路径；只新增修改 `src/control_plane/services/cursor_cli_wrapper.py`、`cursor_runner.py`，并在现有 `tests/test_cursor_cli_wrapper.py`、`test_execution_lifecycle.py`、必要时 `test_executor_sandbox.py` 与三份现有 docs 内补验收。最终候选最多 10 个 code/tests/docs 路径，`PROGRESS.md/BLOCKED.md` 不提交。只允许新建 `/Users/pojian/chief-state/r7k9/`。CLI、Keychain、宿主 HOME、sandbox profile、main、LaunchAgent、四项目、生产 DB/remote 只读；禁止 merge/push/deploy/promote。

## 现状与任务 0

核对 R7 HEAD=`0bf2e89`、main=`13127b9`、工作树实际为 8 个 code/tests/docs 修改加 2 个进度文件；r7k8：print=1、Cursor commit=1、任务 FAILED、authJson=0、Key hit=0。读取 transcript 最终 JSON 的字段形态，但不得复制旧 lease。记录实际路径、顺序和最大风险≤10行；不符即停。

## 任务 1｜移除模型自证

修改 trusted adapter：

1. prompt 只要求严格 scope、单 commit、禁 push/merge/deploy；明确最终文字不作为验收，不再要求 `executor-result`。
2. wrapper 对 CLI stdout 只验证一个外层 JSON object、字段白名单、`type=result`、非 error、进程 exit=0；多对象、额外文字、错误 envelope 仍拒绝。`result` 内层可以是普通文字或任意 JSON，但必须丢弃，不原样输出。
3. `CursorRunner` 的隔离 worktree 路径不得再解析模型的 task/lease/commit/checks。身份取注册任务和 active lease；commit 取 `inspect_execution`；acceptance 只取 `run_chief_verification`。durable `executorResult` 元数据也由 Control Plane 填入。
4. 保留单提交、clean tree、scope、host snapshot、固定 verification、exact import、official report、REVIEW 的全部闸门。

红→绿测试必须复现 r7k8 的错误字段：外层成功、内层为 `type/id/passed`，且单提交正确时应由系统验收到 REVIEW；伪造 task/lease/pass 不得影响系统事实。另证：外层多 JSON/error 失败；无提交、多提交、越界、脏树失败；Chief command 失败不能 REVIEW；内层 secret/narrative 不进 stdout、日志、report。不得 mock Git inspect 或 Chief verification。

## 任务 2｜回归与干净候选

运行：
`PYTHONPATH=src .venv/bin/python -m unittest tests.test_cursor_cli_wrapper tests.test_executor_sandbox tests.test_execution_lifecycle -v`
`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`
`git diff --check`
要求 focused≥61、full≥176、failure/error/skip=0。禁止 skip/todo、删测试、放宽外层 envelope/commit/scope/verification 判据、mock 被测对象或 `|| true`。

从 R7 HEAD 建全新 r7k9 clean runtime clone，只应用最终最多 10 个候选路径并做 1 个 validation-only commit；runtime clean，parent=`0bf2e89`，diff-tree 恰等实际白名单，各 blob 与 R7 工作树一致。任一不符不启动 canary。

## 任务 3｜唯一 canary 与固化

用 r7k9 clean runtime/state/target 经生产入口运行一次同等单文件 canary。要求 `--print=1`、Cursor 单提交、系统从 Git 得到 commit、Chief fixed verification 通过、exact import、official report、状态 REVIEW。模型最终文字无论叙述或错误自定义 JSON都不得成为验收来源。

结束后 `auth.json`（文件/链接/异常类型）=0；可信父进程只输出 r7k9 的 `exactKeyHitCount=0`，不得输出 Key。write allow=2，merge/promote=0，main/LaunchAgent/四项目不变。失败立即停，不重试。

仅全部 PASS 后，amend R7 的最终候选路径；R7 commit tree 必须等于 validation-only tree，相对 main 恰好 1 commit；进度文件不提交，不合并、不激活。

## 规矩

不新增依赖、权限、流程或执行系统。同一验收失败3次即停；失败保留证据，不用人工改 FAILED/REVIEW 状态。

## 完成条件

1. 唯一 canary 到 REVIEW，Git/Chief verification/official report 是唯一验收来源。
2. print=1、authJson=0、Key hit=0、write allow=2、候选 trees 相等、宿主与项目变化=0。

逐项贴脱敏实际输出；只说完成不算。`BLOCKED.md` 空也写“无”。
