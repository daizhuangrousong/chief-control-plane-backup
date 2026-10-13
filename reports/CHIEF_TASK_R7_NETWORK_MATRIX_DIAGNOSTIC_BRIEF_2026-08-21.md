你是执行者，这是 R7 的无凭证网络矩阵诊断，也是唯一任务来源；先读当前 `PROGRESS.md/BLOCKED.md` 和 r7k6 证据，保持 memory 窄修现场不变。目标是解释为什么宿主可访问 `api2.cursor.sh`，而真实 CLI 的 API-key exchange 抛网络错误。全过程不读取 Keychain、不传 API key、不运行 `--print`、不改代码。断线先读进度；拿不准写 `BLOCKED.md` 后停。让步顺序：零凭证 > 可复现根因 > 零仓库变更 > 速度。

## 我替领导拍的板

- 这是一项只读诊断，不是新 canary；外部请求最多 8 次，仅访问 `https://api2.cursor.sh/` 和 `/auth/exchange_user_api_key`。
- exchange 路径不带 Authorization，只用空 JSON；任何 HTTP 状态都算“网络到达”，只有 DNS/TCP/TLS/fetch 异常算网络失败。
- 比较系统 curl 与 CLI 自带 Node，宿主与现有 R6 sandbox，Node 分别带/不带 `--use-system-ca`。
- 证据只记阶段、exit、HTTP 状态、异常类和 `cause.code`；不记 IP、响应正文、header、代理值或完整 stack。

## 界限

Control Plane 代码/docs/tests、R7 HEAD、当前未提交 memory 修复、CLI、Keychain、宿主 HOME、LaunchAgent、四项目全部只读。只允许写 `/Users/pojian/chief-state/r7net/` 和未提交 `PROGRESS.md/BLOCKED.md`。禁止 `security -w`、`CURSOR_API_KEY`、Authorization header、status、login/logout、模型请求、commit/merge/push/deploy。

## 现状与任务 0

已核：r7k6 memory 生效、Keychain timeout 消失、auth.json=0、write allow=2；真实 CLI 在 `exchange_user_api_key` 阶段显示 `Failed to reach the Cursor API`。宿主无 proxy env、`scutil --proxy` 为空；Chief 无凭证 curl `https://api2.cursor.sh/` 得 HTTP 200。CLI debug log显示 Statsig 初始化成功、随后 `analytics.flush.deferred reason=no_token`。先核对这些文件存在，记录测试矩阵与最大泄露风险，≤10 行。

## 任务 1｜八格网络矩阵

使用全新短 clone 和由现有 `prepare_executor_sandbox` 生成的 profile；profile 必须 write allow=2。运行以下组合，每项超时≤15 秒：

1. 宿主系统 curl GET `/`。
2. sandbox 系统 curl GET `/`。
3. 宿主系统 curl POST `/auth/exchange_user_api_key`，空 JSON、无 Authorization。
4. sandbox 同一 POST。
5. 宿主 CLI 自带 Node `fetch` GET `/`，不加 `--use-system-ca`。
6. sandbox 同项。
7. sandbox CLI Node `--use-system-ca` fetch GET `/`。
8. sandbox CLI Node `--use-system-ca` fetch POST exchange，空 JSON、无 Authorization。

Node 小脚本只能输出 `{ok,httpStatus,errorName,causeCode}`；脚本和结果写 r7net。所有进程显式 `env -i`，只给 HOME/TMP/XDG/PATH/LANG、`AGENT_CLI_CREDENTIAL_STORE=memory`，不得继承 proxy、CA、token 或其他宿主变量。

## 任务 2｜归因

生成 `network-matrix.json` 与不超过 3 条结论：

- curl 与 Node 都在 sandbox 失败：外层 profile/系统网络差异；
- curl 成功、Node 失败：Node runtime/CA/fetch 差异；
- Node 仅 `--use-system-ca` 失败：系统 CA 开关；
- 八项均拿到 HTTP：网络本身正常，r7k6 错误只存在于带真实 key 的 exchange 流程，禁止再声称缺 HTTPS_PROXY。

每条结论必须绑定矩阵格编号。不要提出代码修复，交 Chief 决策。

## 规矩

不许输出响应正文/header/IP，不许读取任何 secret，不许为了拿 2xx 伪造 Authorization，不许安装工具、改 DNS/代理/证书/沙盒，不许 `|| true`。任何脚本先扫描确认不含 `CURSOR_API_KEY`、`security`、`Authorization` 再运行。

## 完成条件

1. 8 格都有机器可判结果，能区分 DNS/TLS/HTTP/Node/system-CA/外层 sandbox，结论≤3 条。
2. `printCalls=0`、Keychain reads=0、仓库 diff 与开工完全相同、宿主/线上/四项目零变化。

贴脱敏实际输出，只说完成不算。`BLOCKED.md` 空也写“无”。
