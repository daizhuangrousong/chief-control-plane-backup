你是执行者，这是 R7 的单次认证交换诊断，也是唯一任务来源；保持当前 memory 修复现场不变。网络矩阵已证明 host/sandbox、curl/Node、±system-ca 都能到 `api2.cursor.sh`，空 exchange 返回 401。目标是只运行一次与 CLI 相同的真实 User API Key exchange，区分 Key header 形态、服务端拒绝和 CLI memory 流程问题；不调用模型、不运行 `--print`、不保存 token。断线先读进度；拿不准写 `BLOCKED.md` 后停。让步顺序：凭证零泄露 > 一次可判诊断 > 零仓库变更。

## 我替领导拍的板

- 使用现有 Keychain loader 和 bundled Node，在 R6 sandbox + memory store 中直接 POST `/auth/exchange_user_api_key` 一次。
- 这是认证请求，不是 Agent/model canary；最多 1 次 authenticated exchange，禁止重试。
- 响应 access/refresh token 只允许在 Node 进程内检查字段存在，随后置空并退出；不得传给父进程、写盘、哈希或输出长度/前后缀。
- 只记录 shape 布尔值、HTTP 状态类别、token schema 布尔值、异常名与 cause code。

## 界限

代码/docs/tests、当前 memory diff、R7 HEAD、CLI、Keychain 值、宿主 HOME、LaunchAgent、四项目全部只读。只允许写 `/Users/pojian/chief-state/r7auth/` 和 `PROGRESS.md/BLOCKED.md`。禁止输出 Key、Authorization、response body/header、token、账号、长度、hash；禁止 status/login/logout、模型请求、commit/merge/push/deploy。

## 现状与任务 0

已核：r7k6 memory 生效、auth.json=0、write allow=2；r7net 8/8 得到 HTTP，exchange 无认证=401；真实 CLI 带 Key 时抛 `AuthNetworkError`。先核对这些证据和代码 diff SHA 未变；写入顺序与最大泄露风险≤10行。不带 `-w` 确认 Keychain 项存在。

## 任务 1｜本地 header 形态

可信父进程用 loader 取 Key，仅注入 sandboxed bundled Node。Node 不联网，检查并只输出：

- `prefixClassValid`：是否符合 CLI User Key 的 ASCII token 类；
- `asciiPrintable`：是否全部为可打印 ASCII；
- `noWhitespaceOrControl`：是否无空白/控制字符；
- `headerConstructed`：`new Headers({Authorization: "Bearer " + key})` 是否成功。

不得输出具体失败字符、位置或长度。检查后删除 env 引用并退出。任一为 false，停止，不运行任务 2。

## 任务 2｜单次真实 exchange

仅四个布尔值全 true 时，在同一短 clone、同一 R6 profile、`AGENT_CLI_CREDENTIAL_STORE=memory` 下，用 bundled Node 原生 fetch POST `https://api2.cursor.sh/auth/exchange_user_api_key`：空 JSON body，Authorization 仅从内存 key 构造。超时≤20秒。

输出仅允许：`requestReached`、`httpStatusClass`（2xx/4xx/5xx）、`tokenSchemaValid`（2xx JSON 同时含非空 accessToken/refreshToken）、`errorName`、`causeCode`。不得输出具体 status 之外的正文；解析后立刻清空对象和 token 引用。父进程扫描脚本、stdout/stderr、r7auth，确认不存在 `crsr_`、Bearer 值、access/refresh token 值或 `CURSOR_API_KEY=`。

## 任务 3｜机器归因

只允许以下结论之一：

- shape/header false：Keychain 值含复制/格式异常；
- exchange 4xx：服务端拒绝该 Key；
- exchange 2xx + schema true：Key 与网络正常，r7k6 根因在 Cursor CLI exchange 后的 credential-manager/memory 流程；
- exchange 异常/5xx：记录 error/cause 或 5xx，网络/服务端瞬时失败，禁止猜测。

## 规矩

不许日志调试输出 secret，不许 curl argv header，不许第二次 exchange，不许把 token 写临时文件，不许 `|| true`。脚本运行前静态扫描不得包含任何真实 secret；运行后再扫一次。

## 完成条件

1. 四项 shape 布尔值和唯一 exchange 得出一个机器归因；失败路径按规则提前停止也算合格。
2. `printCalls=0`、authenticatedExchangeCalls≤1、token/key 落盘=0、仓库 diff 与开工一致、宿主/线上/四项目零变化。

贴脱敏实际输出，只说完成不算。`BLOCKED.md` 空也写“无”。
