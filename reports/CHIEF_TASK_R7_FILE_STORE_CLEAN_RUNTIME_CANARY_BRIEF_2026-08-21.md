你是执行者，这是 R7 file-store 的干净 runtime 续跑，也是唯一任务来源；中途没人可问，拿不准写 `BLOCKED.md` 后停。断线先读 `PROGRESS.md`，每项完成即更新。上一轮 `--print=0`，唯一问题是 Chief 错把未提交 overlay 当 runtime；本轮用一次性本地 commit 提供干净候选树，不放宽生产 clean-check。冲突时：凭证零残留 > 候选树一致 > 唯一 canary > 速度。只有“只允许/不许”是硬边界。

## 我替领导拍的板

- r7k7 不是 Cursor 失败，不消耗真实 canary 名额；本轮仍最多 `--print=1`。
- 一次性 runtime clone 可有 1 个 validation-only 本地 commit；不得进入 main、R7 分支或 remote。
- canary PASS 后，才把相同候选树 amend 到 R7；两个 tree hash 必须相等。

## 界限

R7 工作树只允许保留现有 3 个 source、3 个 tests、3 个 docs 候选改动及 `PROGRESS.md/BLOCKED.md`；不得再改实现或判卷标准。只允许新建 `/Users/pojian/chief-state/r7k8/`。CLI、Keychain 值、宿主 HOME、sandbox profile、main、LaunchAgent、Julius/Director/Eval、生产 DB/remote 只读；禁止 merge/push/deploy/promote。不得输出、复制、哈希或记录 Key/token/auth.json 内容。

## 现状与任务 0

核对 R7 HEAD=`0bf2e8981acab9b7854a3d82bbfce13169b4c962`、main=`13127b9c26e8a0252d78282f32e165a28aa848b2`、工作树恰有上述 11 个修改路径；r7k7 evidence 为 runner=2、print=0、task=READY、authJson=0。记录候选 diff SHA 和九个候选文件清单；不符即停。写≤10行开工回执。

## 任务 1｜建立干净候选 runtime

从 R7 HEAD 新建独立短路径 runtime clone；只把九个 code/tests/docs 候选文件的精确 diff 应用进去，排除 `PROGRESS.md/BLOCKED.md`，创建 1 个 validation-only 本地 commit。要求：

- runtime `git status --porcelain` 为空，HEAD 的 parent 是 `0bf2e89`；
- runtime 九文件 blob SHA 与 R7 工作树逐一相同；其余 tracked 文件与 R7 HEAD 相同；
- `git diff-tree --no-commit-id --name-only -r HEAD` 恰好九个白名单路径。

任一不符停止，不启动 canary。

## 任务 2｜从候选 runtime 重验

在干净 runtime 运行：
`PYTHONPATH=src .venv/bin/python -m unittest tests.test_cursor_cli_wrapper tests.test_executor_sandbox tests.test_execution_lifecycle -v`
`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`
`git diff --check HEAD^ HEAD`
要求 focused≥61、full≥176，failure/error/skip=0，runtime 仍 clean。禁止 skip/todo、放宽断言、删测试、mock 被测清理函数或 `|| true`。

## 任务 3｜唯一真实 canary

仅前两项成立后，用该 clean runtime 和全新 r7k8 state/target，经生产入口、Keychain 内存注入、固定 file store、短 clone HOME、R6 sandbox 运行一次。任务只新增 `reports/R7_REAL_CURSOR_CANARY.md`。要求 `--print=1`、独立 clone 单 commit、父进程 exact import、固定 verification、official report、状态 REVIEW；merge/promote=0，目标 main/宿主/四项目不变。

无论成功/失败，检查所有 r7k8 路径中 `auth.json`（含文件、链接、异常类型）不存在。可信父进程只在内存读取 Key，扫描 r7k8 stdout/stderr/log/state/clone 是否含该 Key 的精确值，只输出 `exactKeyHitCount`，必须为 0；不得输出 Key。若认证、清理、契约或超时失败，立即停，不重试。

## 任务 4｜仅 PASS 后固化

只有 REVIEW 全成立，才在 R7 工作树以九个候选文件 amend 原 commit；排除进度文件。要求 R7 commit tree hash 与 validation-only commit tree hash 完全相同，R7 相对 main 恰好 1 commit；不删除 r7k8 证据，不合并、不激活。

## 规矩

不新增依赖、权限、流程或执行系统。同一验收失败 3 次即停；比开工差则只恢复本轮 r7k8 临时现场，不触碰原候选改动。

## 完成条件

1. canary 到 REVIEW：`--print=1`、单 commit/import/official report 成立；或唯一尝试按止损带证据停。
2. `auth.json=0`、`exactKeyHitCount=0`、write allow=2、两棵候选 tree 相等、main/LaunchAgent/四项目变化=0。

逐项贴脱敏实际输出；只说完成不算。`BLOCKED.md` 空也写“无”。
