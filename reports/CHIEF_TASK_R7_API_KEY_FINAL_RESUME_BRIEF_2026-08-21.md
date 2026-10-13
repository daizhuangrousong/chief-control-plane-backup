你是执行者，这份文档是同一 R7 的最终续跑任务；先读现有 `PROGRESS.md/BLOCKED.md` 与两份 R7 Chief Review，接着做，不建 R7.1。这里要按 Owner 批准方案把专用 API key 从 Keychain 仅注入可信父进程，HOME 恢复 clone，再让真实 Cursor canary 到 REVIEW。让步顺序：密钥不落地 > 只写 clone > 真实交付 > 速度。“只允许/不许”违反即失败。

## 我替领导拍的板

- Keychain 已由 Owner 写入，Chief 只验存在：service=`com.pojian.chief-cursor-api`、account=`pojian`；不得读取后打印。
- 官方无头认证用 `CURSOR_API_KEY`；宿主浏览器登录不再供生产 Runner 使用。
- 继续 `/Users/pojian/repos/director-control-plane-r7-production-wiring`，amend `c37ed84`，最终相对 main 仍 1 commit。
- 全新 stateRoot；真实 `--print` 最多 2 次，同因两次失败即停。

## 界限

沿用 R7 全部白名单；可新增 `src/control_plane/services/cursor_keychain.py`，并改现有 R7 测试/文档/plist example。允许写 `/Users/pojian/chief-state/control-plane-r7-api-key/`。`PROGRESS.md/BLOCKED.md` 只作未提交记录。除可信父进程捕获 `/usr/bin/security` 的内存 stdout 外，禁止把 key/派生值/哈希转发或写入 argv、plist、JSON、仓库、stateRoot、task、对外 stdout/stderr、日志或证据；禁止 `env`/`printenv`/进程转储；禁止 main、R4/R6、live LaunchAgent、四项目仓、生产 DB、remote、push/merge/deploy。sandbox write profile 仍仅 clone + `/dev/null`。

## 现状与任务 0

实测：R7=`c37ed84`、相对 main 1 commit；Chief 169/0/0；浏览器认证 + 宿主 HOME 的真实 run 因写 `~/.cursor/projects` EPERM；宿主零变化。只用不带 `-w` 的 `security find-generic-password` 验证项目存在，输出丢弃；不读值。核对 main=`13127b9`、LaunchAgent hash、工作树仅进度文件脏后，PROGRESS ≤10 行写顺序/风险；不符即停。

## 任务 1｜可信 Keychain 注入

实现严格 loader：只调用系统 `/usr/bin/security find-generic-password -w -s <service> -a <account>`，argv 只含非秘密元数据，`shell=False`、短 timeout；非零、空值、锁定或异常在 DB/claim/Executor 前 fail closed，错误不得含 stdout/key。生产入口必须要求 service/account 参数，从 Keychain 取得值后只放入内存环境 `CURSOR_API_KEY`，不改全局环境；传给 `CursorRunner`，再由既有 allowlist 进入 sandbox。不得把 key 放进 Runner 对象 repr/结果/日志。红→绿测试用假 security 证明缺 key Executor=0、成功只注入 child env、日志/文件无 canary secret。

## 任务 2｜恢复 clone HOME 与隔离

撤销宿主 HOME 方案：HOME/TMP/TEMP/XDG/Python cache 全回独立 clone；删除宿主 HOME 例外代码/文档，恢复并加强测试。API key 存在时 `status` 不依赖浏览器登录；clone 内 `.cursor/projects` 可写。真实 sandbox 攻击 runtime/state/目标 main/目标 `.git`/宿主 HOME/child/symlink 仍全部 errno=1，profile write allow 行恰好 2；clone commit 仍成功。

## 任务 3｜真实 canary 与收口

全新一次性目标、DB/outbox/inbox/report/pool；经生产入口和真实 Cursor 只新增 `reports/R7_REAL_CURSOR_CANARY.md`。要求 `--print`≤2、独立 clone 单 commit、严格解包实际外层 JSON、父进程 exact import、固定 verification、official report、状态 REVIEW；宿主与目标 main 零变化，merge/promote=0。随后全测≥169/0/0，单跑 keychain/sandbox/production-entry，`git diff --check`；`git commit --amend --no-edit`，相对 main 恰好 1 commit。证据只记存在/调用次数/状态/SHA，不记 key 或其哈希。

## 规矩

禁止 skip/todo、删/放宽断言、mock 真实 canary/sandbox、`|| true`、宿主 `.cursor` 写允许、复制登录资料、在命令行放 key、把 real Cursor 换 fake。最多两次 canary；用完即停，不再窄修或激活。

## 完成条件

1. 专用 Keychain key 不落地、不泄露；真实 Cursor 在 clone HOME 下单 commit 到 REVIEW，宿主写攻击仍全拒绝。
2. R7 最终 1 commit、全测≥169/0/0；main/R4/R6/live LaunchAgent/四项目仓零变化，外部动作仅≤2次 canary。

每条贴脱敏实际输出；只说完成不算。BLOCKED 空也写“无”。
