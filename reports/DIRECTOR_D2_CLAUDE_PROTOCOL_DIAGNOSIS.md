# DIRECTOR D2 — Claude `protocol_not_supported` 只读诊断

- 角色：独立诊断员（只读，非生产执行器）
- 仓库：`/Users/pojian/repos/director`（`main` @ `99945ff`，工作区 dirty）
- 运行中后端：容器 `director-agent-backend`，启动 `2026-08-19T03:19:24Z`，无 `--reload`；`backend/` bind-mount 到 `/app`
- 健康探针：`GET http://127.0.0.1:8000/health` → `commit=dirty`，`env_commit=5fdc4f557691285604790ffcfdb99e03d660d655`，`git_head=99945ff101dbe44020e363514daeed21c6217402`
- 本报告写于 control-plane，未修改 Director 任何文件，未重启容器，未发起真实模型调用，未写库

---

## 结论摘要（给 Chief 直接转任务）

默认 Claude 主模型走 Packy 兼容中转的 **Chat Completions**。代理明确拒绝 `claude-opus-5` / `claude-sonnet-5` 的 chat 协议。脏树里的 `ClaudeAdaptiveProvider` 会再打 **Anthropic Messages**；Messages 才是成功时实际用的协议。Responses **不是** Claude 路径。

`protocol_not_supported` 之后没有 sleep。额外等待来自：① 必失败的 chat  hop；② 同一次 `generate()` 里对 Messages 的重试（成功则多 2–8s 级；403 则合计 1.7–11s；挂起则打满 `ClaudeProvider` 的 **180s** timeout）；③ fallback_chain 第一环又是同一个 Claude provider，把 ①② 再跑一遍。

只改 `CLAUDE_API_FORMAT=anthropic` **不够且危险**。最小修复是代码：Claude 默认 Messages、去掉无意义的 chat 首跳、保留 URL 去 `/v1` 规范化。现有脏改已含半成品，不能原样上线。

---

## 1. 哪个 provider / model / endpoint / 协议组合触发 `protocol_not_supported`

**触发组合（已证明）**

| 项 | 值 | 证据 |
|---|---|---|
| Provider 名（router / 日志） | `claude` | `model_call_logs.provider`；`ProviderRegistry` 注册名 `llm_provider.py:863-869` |
| 运行时类 | `ClaudeAdaptiveProvider` | `docker exec … python -c "… get_provider_for('claude'); print(type(p).__name__)"` → `ClaudeAdaptiveProvider` |
| 默认主模型 | `claude-opus-5` | `SELECT default_provider, default_model FROM model_configs WHERE task_type='script_generation'` → `claude` / `claude-opus-5`（`updated_at=2026-08-18 08:19:23+00`） |
| 链上第二 Claude | `claude-sonnet-5` | 同上 `fallback_chain` 第一项 |
| 代理 base | `https://slb-v1.api.fan/v1` | 容器 env `CLAUDE_BASE_URL`（`docker inspect`，已去掉密钥） |
| 格式开关 | `CLAUDE_API_FORMAT=openai_compatible` | 同上容器 env；`core.py:43` 默认值 |
| 失败协议 | OpenAI Chat Completions | 错误体 `type=packy_api_error`，`code=protocol_not_supported` |
| 失败 URL | `{CLAUDE_BASE_URL}/chat/completions` = `https://slb-v1.api.fan/v1/chat/completions` | `OpenAICompatibleProvider.generate` `llm_provider.py:223-224` |
| 鉴权 | `Authorization: Bearer` | `llm_provider.py:175-178` |
| 错误原文 | `模型 claude-opus-5 不支持 chat completions 协议` / `模型 claude-sonnet-5 不支持 chat completions 协议` | `model_call_logs.error_message`，样本 `2026-08-25 04:59:01+00` request id `01M0VMJPE4JWW1Y41JPZ54A1TH` |

**可复跑只读命令**

```bash
docker inspect director-agent-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | rg '^CLAUDE_(BASE_URL|MODEL|API_FORMAT)='
docker exec director-agent-postgres psql -U director_agent -d director_agent -c \
  "SELECT task_type, default_provider, default_model, fallback_chain FROM model_configs ORDER BY task_type;"
docker exec director-agent-postgres psql -U director_agent -d director_agent -c \
  "SELECT created_at, model_name, LEFT(error_message, 280) FROM model_call_logs WHERE error_message ILIKE '%protocol_not_supported%' AND provider='claude' ORDER BY created_at DESC LIMIT 5;"
```

**Claude 成功时的第二跳（不是触发码，但是同一组合的另一半）**

- URL：`https://slb-v1.api.fan/v1/messages`（`_normalize_anthropic_base_url` 去掉末尾 `/v1` 后再拼 `/v1/messages`，`llm_provider.py:473-478,668,698-699`）
- 鉴权：`x-api-key` + `anthropic-version: 2023-06-01`（`llm_provider.py:699-705`）
- 成功样本 metadata：`protocol=messages`，`status=200`，`stop_reason=end_turn`（`2026-08-25 04:59:01+00` `claude-sonnet-5`）

**时间范围**：Claude 行里最早的 `protocol_not_supported` 是 `2026-08-14 09:06:24+00`，最近是 `2026-08-25 04:59:01+00`，共 27 行（只读 `COUNT`）。

**UNKNOWN**：chat  hop 的 HTTP 状态码。旧行 `extra_metadata` 为空；新行只记下了 *second* hop 的 `provider_metadata.status`（Messages 403），没有单独存 chat  hop 的 status。

---

## 2. 当前请求实际使用 Chat Completions、Messages 还是 Responses

**Claude 路径不使用 Responses。** Responses 只存在于 `OpenAIResponsesProvider` / `OpenAIAdaptiveProvider`（`llm_provider.py:275-379,566-633`），注册名 `openai`。

运行中的 Claude 一次 `generate()` 顺序（`ClaudeAdaptiveProvider._generate_protocols`，`llm_provider.py:428-448`）：

1. **先 Chat Completions**（`self._preferred` 默认 `"chat"`，`llm_provider.py:407`）
2. 若 `_is_protocol_error(error_message)` 命中 `protocol_not_supported` 等 marker（`llm_provider.py:532-546`），**再打 Messages**

**成功落库的 Claude 调用（有 metadata 的窗口）全部是 Messages，0 条 Chat Completions：**

```sql
SELECT extra_metadata->'provider_metadata'->>'protocol' AS protocol, COUNT(*)
FROM model_call_logs
WHERE provider='claude' AND success AND created_at >= '2026-08-18'
  AND extra_metadata ? 'provider_metadata'
GROUP BY 1;
-- 只读实测：全部 protocol = messages
```

样本：

- `2026-08-18 08:15:15+00` `claude-opus-5` primary OK，`protocol=messages`，`status=200`
- `2026-08-25 04:59:01+00` `claude-sonnet-5` fallback OK，`protocol=messages`，`status=200`

`2026-08-18 07:35` 及更早的 Claude 失败行只有 `protocol_not_supported` JSON、没有 `both protocols failed`、也没有 `provider_metadata.protocol`：那是 **尚未走 Adaptive**、只打 Chat Completions 的阶段（容器启动于 `2026-08-19T03:19:24Z`，`llm_provider.py` mtime `2026-08-18T17:07:39Z`）。

**因此：每个默认 Claude 请求都会先打 Chat Completions（必失败），成功时实际产出文本的是 Messages。**

---

## 3. 错误发生后为什么仍会等待再 fallback，额外延迟是多少

没有 backoff / sleep。等待 = 同步 HTTP。

### 3.1 协议层（`ClaudeAdaptiveProvider`，发生在 router fallback 之前）

`protocol_not_supported` 被 `_is_protocol_error` 判定为可换协议（`llm_provider.py:438,542-546`），于是 **立刻**再打 Messages。Messages timeout 硬编码 **180s**（`llm_provider.py:718`）。

`get_provider_for()` **每次** `ProviderRegistry.from_settings()`（`llm_provider.py:922-929`），`_preferred` 无法跨请求保留，所以 **每个请求、链上每个 Claude hop 都从 chat 再来一遍**。

`_attempt_provider` 只把 `llm_resp.latency_ms` 累加进去（`model_router.py:93`）。Adaptive 返回的是 **最后一跳** 的 `latency_ms`，chat  hop 的墙钟被吃掉但用户仍要等。

### 3.2 router 层（`fallback_chain`）

`protocol_not_supported` **不在** `_RETRYABLE_KEYWORDS`（`model_router.py:39`），同一 provider 不会因该错误重试。主模型失败后按链走：

`claude-opus-5` → `claude-sonnet-5` → MiniMax → Doubao → DeepSeek  
（`model_configs.fallback_chain`，与 `db/init/020_fallback_chain.sql:27-30` 一致）

第二环仍是 `claude`，再付一次 chat + Messages。

### 3.3 测得延迟（`model_call_logs`，近 14 天；`latency_ms` 在 router 里是 **链上累计值**，`model_router.py:201-207`）

| 场景 | n | 延迟 | 含义 |
|---|---|---|---|
| Adaptive 之前，仅 chat `protocol_not_supported`，opus 主跳 | 10 | p50 **7205ms**（min 2033，max 15087） | 孤立 chat  hop 成本 |
| 同场景 sonnet 作为 fallback | 7 | p50 **21776ms** | 含主跳累计 |
| Adaptive 之后，chat 失败 + Messages **403**（Cloudflare / packy 403） | opus 主跳 1717 / 6100 / 11091ms | 换协议后的短失败 |
| Adaptive 之后，chat 失败 + Messages **`The read operation timed out`** | opus **181025–181329ms** | 打满 180s Messages timeout 再交给链 |
| 同上，sonnet 再 timeout | **362401 / 367641ms** | 两个 Claude hop 各 ~181s |

最新生产样本 `chain_id=29925835-7bbf-403f-a785-86257cdcf481`（`2026-08-25 04:59:01+00`）：

1. opus：chat `protocol_not_supported` → Messages `status=403` Cloudflare ray `a30806c3f8b84b48-PDX`，累计 **6100ms**
2. sonnet：再次 chat 失败后 Messages **200**，累计 **66177ms**（含上一跳）

`GET /api/config/generation-health?window=100`：`fallback_rate=0.65`，`real_llm_success_rate=0.07`。近 14 天带 `chain_id` 的 32 次请求：主模型成功 **6**，靠 fallback 成功 **25**，全失败 **1**。

**额外延迟怎么报给开发：**

- 稳定可报的 chat  hop：约 **2–8s**（p50 7.2s，Adaptive 前孤立样本）
- 403 路径：chat + Messages 合计约 **2–11s** 后才进入 MiniMax
- timeout 路径：`protocol_not_supported` 之后再等 **~180s**（再乘一次 sonnet ≈ **360s**）才到非 Claude 兜底

脏树 Adaptive 在 Messages 挂起时 **比 HEAD 只打 chat 更慢**：HEAD 会在 ~7s 后进入 MiniMax；现在可能先烧 180s×2。

---

## 4. 脏工作区是否已有相关修复（只列，不改）

**有。半成品，已挂进正在跑的后端（文件 mtime 早于容器启动）。**

### 4.1 相关脏文件

| 文件 | 逻辑 | 风险 |
|---|---|---|
| `backend/app/services/llm_provider.py` | 新增 `ClaudeAdaptiveProvider`：chat → Messages；`_normalize_anthropic_base_url`；`openai_compatible` 时注册 Adaptive；有 `claude_fallback_api_key` 时 `anthropic` 格式也包 Adaptive | `_preferred` 默认仍是 `"chat"`；`get_provider_for` 不缓存；Messages 180s timeout；`anthropic`+fallback key 仍先打 chat（`llm_provider.py:872-880`）；成功时丢掉 chat  hop 的 latency |
| `backend/app/core.py` | 默认 `claude_api_format="openai_compatible"`；新增 `claude_fallback_api_key` | 与 HEAD 默认 `"anthropic"` 相反；只改 env 不够 |
| `.env.example` / `docker-compose.yml:84` / `deploy/docker-compose.prod.yml:79` | 示例/compose 默认 `CLAUDE_API_FORMAT=openai_compatible`，`CLAUDE_BASE_URL` 示例 `https://slb-v1.api.fan/v1` | HEAD compose 默认是 `anthropic`。只改 format 到 `anthropic` 且无 normalize 会打到 `/v1/v1/messages`（HEAD `llm_provider.py` 用 `base_url.rstrip('/')+/v1/messages`） |
| `backend/tests/test_r3_empty_script_fix.py` | `TestClaudeAdaptiveProtocolRetry` 4 个用例 | 注释写「切 Responses」（L284），实际切的是 Messages；**没有**「默认 Messages / 不去 chat」的测试；没有 URL normalize 测试 |
| `backend/app/schemas/model_config.py` / `backend/app/api/config.py` | fallback 允许 `glm`；providers 列表加 GLM | 与本协议 bug 无关 |

### 4.2 脏改已证明有效的部分

- Messages 能出稿（`2026-08-18 08:15` 起成功行 `protocol=messages`）
- URL 规范化：运行时 `messages base = https://slb-v1.api.fan`（已 `docker exec` 打印）
- 现有单测：`docker exec -w /app director-agent-backend python -m pytest tests/test_r3_empty_script_fix.py tests/test_model_router_raw_fallback.py tests/test_model_router_json.py -q` → **38 passed, 1 skipped**

### 4.3 脏改未解决、且会加重等待的部分

1. 每个请求仍先打必失败的 Chat Completions  
2. fallback_chain 第一环再打一遍 Claude  
3. Messages 挂起时付满 180s 再降级  
4. 二次 key（aws-q / cc-sale「无可用渠道」）是另一类错误，见 `2026-08-18 09:44–10:24`，**不是** `protocol_not_supported`

---

## 5. 最小修复：改配置还是改代码（文件 + 测试）

**必须改代码。禁止只改配置作为本任务的完成定义。**

### 为什么配置不够

| 只改配置 | 结果 |
|---|---|
| `CLAUDE_API_FORMAT=anthropic` + 当前脏树 + 已配 `CLAUDE_FALLBACK_API_KEY` | 仍走 `ClaudeAdaptiveProvider`，仍先 chat（`llm_provider.py:872-880`） |
| 同上，HEAD 提交树、无 fallback key | `ClaudeProvider` 直打 `{base}/v1/messages`；`CLAUDE_BASE_URL` 已含 `/v1` → **`/v1/v1/messages`** |
| 把默认模型改成 MiniMax | 绕过 Claude，不修协议；超出「最小修复」且改变产品默认 |

### 最小代码改动（建议单 PR，只动协议）

1. **`backend/app/services/llm_provider.py`**
   - `ClaudeAdaptiveProvider._preferred` 默认 `"messages"`  
   - 或对 `claude-opus-5` / `claude-sonnet-5` **根本不打 chat**  
   - `claude_api_format != openai_compatible` 时只注册 `ClaudeProvider`（key fallback 另议，不要为此先打 chat）  
   - 保留 `_normalize_anthropic_base_url`  
   - 非首选协议探测用短 timeout（建议 ≤5s），**不要**用 180s 去探测已拒绝的 chat  
   - 可选：进程内缓存 `ProviderRegistry`，让 `_preferred` 跨请求有效（次要，若已默认 Messages 则非必须）
2. **不要**把「从 fallback_chain 去掉 sonnet」当作唯一修复；那只减少重复 hop。可作同一 PR 的配置/SQL 附带项：`script_generation` / `script_outline` 的 chain 第一项改为 MiniMax（需 Owner 确认，因为会改变「第二 Claude」产品语义）
3. **测试（同文件或 `backend/tests/test_r3_empty_script_fix.py`）**
   - 默认 `_preferred=="messages"`，成功路径 **0 次** chat `generate`  
   - `protocol_not_supported` 若仍允许 chat 探测，探测 timeout 必须短  
   - `_normalize_anthropic_base_url("https://slb-v1.api.fan/v1") == "https://slb-v1.api.fan"`  
   - `anthropic` 格式 + fallback key **不得**先 chat  
   - 修正 L284 错误注释（Responses → Messages）

HEAD 对照：提交树在 `openai_compatible` 下只注册 `OpenAICompatibleProvider`（`git show HEAD:backend/app/services/llm_provider.py` 约 L706-714），**不会**切 Messages。脏树不能当已完成修复合并。

---

## 6. 零生产写入、最多一次真实探针的验收

**本诊断未做真实探针。** 下面给 Chief / 执行器。

### A. 无写入、无探针（必做）

```bash
# 单测
docker exec -w /app director-agent-backend python -m pytest \
  tests/test_r3_empty_script_fix.py tests/test_model_router_raw_fallback.py -q

# 只读：修复后新行不应再以 chat 为首跳成功协议
docker exec director-agent-postgres psql -U director_agent -d director_agent -c "
SELECT created_at, model_name, success, fallback, latency_ms,
       extra_metadata->'provider_metadata'->>'protocol' AS protocol,
       LEFT(error_message, 160)
FROM model_call_logs
WHERE provider='claude'
ORDER BY created_at DESC
LIMIT 20;
"
```

通过标准（有新流量之后）：

- 新成功 Claude 行：`protocol=messages`（或不再出现 Claude 行，若已改默认模型——那是另一决策）
- 新失败行：`error_message` **不应**再以 chat `protocol_not_supported` 作为 `both protocols failed; first=...` 的常规形态
- 主跳失败 p50 不应再出现 ~181s 的 Messages timeout（除非 Messages 本身在出稿）

### B. 最多一次真实探针（需 Owner 书面点名；本诊断未执行）

不要走 `generate_structured_script` / `_run_with_fallback_chain`：那会 **INSERT `model_call_logs`**（`model_router.py:783-808`）。

若必须探针：在 **非生产 DB 写入** 前提下，对 `https://slb-v1.api.fan/v1/messages` 打一条最小 `max_tokens` 请求（鉴权与线上相同）。`file_agent` no-log 测试 **不支持 claude**（`file_agent_model_service.py:1389`）。

探针后仍用 A 的 SELECT 看是否误走了 router。

---

## 7. 修复失败如何回滚

| 已落地的改动 | 回滚 | 不要做 |
|---|---|---|
| 仅把 `_preferred` 改成 messages | 改回 `"chat"` 并重启后端（需 Owner；本诊断禁止重启） | 不要在 HEAD 无 normalize 时把 `CLAUDE_API_FORMAT` 打成 `anthropic` |
| 合并了整份脏 `llm_provider.py` | `git checkout HEAD -- backend/app/services/llm_provider.py` 会回到「只 chat」——`protocol_not_supported` 会回来，但 timeout 会从 180s 降到 ~7s 再进 MiniMax | 不要回滚 MiniMax 链；那是现在的安全网 |
| 改了 `model_configs.fallback_chain` | `UPDATE` 回 `020_fallback_chain.sql` 的 JSON（这是写库，本诊断未做） | — |
| 运行时已是 dirty Adaptive | 容器仍 bind-mount 脏文件；回滚代码后需重启才能卸载（本诊断不重启） | 不要 `compose down` / 动 `/Volumes/KESU` |

**生产安全网（已在库里，回滚协议修复后仍在）：** MiniMax / Doubao / DeepSeek 链。近 14 天 25/32 次请求靠 fallback 成功，多数是 `minimax/MiniMax-M3`。

---

## 8. 与 Director D1 分支可能重叠的文件

D1：`feat/director-health-truth-d1` @ `/Users/pojian/chief-runtime/director-health-truth-d1`  
`git diff --name-only main...feat/director-health-truth-d1`：

- `BLOCKED.md`
- `PROGRESS.md`
- `backend/app/api/monitoring.py`
- `backend/tests/test_monitoring_truth.py`
- `reports/DIRECTOR_D1_HEALTH_TRUTH.md`

与当前 dirty 工作区 **同路径交集：空**（`comm -12` 无输出）。D1 工作树干净。

**相邻、合并时需人工看一眼（不是同一文件）：**

| Dirty（本协议 / 健康指纹） | D1 |
|---|---|
| `backend/app/main.py`（`/health` → `runtime_fingerprint`，L30-35） | D1 的 `main.py` 仍返回 `APP_COMMIT_SHA`（D1 相对 `main` 未改此文件；若先合 dirty 再合 D1 无冲突，顺序反过来 D1 基线仍是旧 `/health`） |
| `backend/app/api/config.py`（providers 加 glm） | D1 `monitoring.py` 的 `director_agent.generation_health` / `model_router` 探针（`monitoring.py:40-41,304-306`） |
| dirty `docker-compose.yml` `CLAUDE_API_FORMAT=openai_compatible` | D1 工作树 compose 仍是 HEAD 的 `anthropic` 默认，但 **D1 commit 未改 compose** |

协议修复 PR **不应**把 D1 的 `monitoring.py` 卷进来。

---

## 相邻发现（非 D2 范围，禁止猜测为根因）

`openai/gpt-5.6-terra` 在 fallback 上也出现 `protocol_not_supported`（Chat Completions）以及 `both protocols failed; second=protocol_not_supported`（`OpenAIAdaptiveProvider` 的 Responses↔chat）。样本最早 `2026-08-05`。这是 **另一个 provider**，不要塞进本 Claude 最小修复。

`2026-08-18 09:44–10:24` 的 `分组 aws-q / cc-sale 无可用渠道（distributor）` 是渠道/分组问题，marker 走 `_is_channel_unavailable_error`，不是 `protocol_not_supported`。

---

## 可复跑命令清单

```bash
# 运行身份
curl -sS http://127.0.0.1:8000/health
curl -sS 'http://127.0.0.1:8000/api/config/generation-health?window=100'

# 进程内 Claude 类（读代码，不调模型）
docker exec director-agent-backend python -c "from app.services.llm_provider import get_provider_for; p=get_provider_for('claude'); print(type(p).__name__, getattr(p,'_preferred',None), getattr(p,'_chat',None)._base_url, getattr(p,'_messages',None)._base_url)"

# 只读 SQL
docker exec director-agent-postgres psql -U director_agent -d director_agent -c "
SELECT provider, model_name, success, fallback, COUNT(*) n, ROUND(AVG(latency_ms)) avg_ms
FROM model_call_logs WHERE created_at >= NOW() - INTERVAL '14 days'
GROUP BY 1,2,3,4 ORDER BY n DESC;
"
```

单测已在容器内跑过：`38 passed, 1 skipped`（`test_r3_empty_script_fix.py` + router 测试）。

---

## 停止条件

诊断完成。未改文件、未开分支、未 commit、未重启、未探针、未写库。
