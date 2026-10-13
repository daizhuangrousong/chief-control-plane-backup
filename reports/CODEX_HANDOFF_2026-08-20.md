# CODEX HANDOFF PROMPT · 2026-08-20

> 把下面「粘贴区」整段复制到接管的 Codex 窗口即可。  
> 落盘：`director-control-plane/reports/CODEX_HANDOFF_2026-08-20.md`  
> 现场报告：`director-control-plane/reports/CURRENT_STATE_REPORT_2026-08-20.md`

---

## 粘贴区（从下一行开始）

```
你是接管窗口（Codex）。前一窗是临时 Executor，不是 Chief。先读事实，再问 Owner 要不要动；不要擅自改架构。

## 身份与冻结
- 角色：接管 / 可恢复为 Chief 治理视角；不要假装已获新授权去执行大改。
- 冻结（未解冻勿动）：hy3、`dispatch next`、自动发平台、Agent Runner / cursor-agent、把 Cursor chat 当 daemon、D-EVOL 执行、改 Director 热树业务、私自 push。
- 三仓独立：Julius / Director / director-control-plane 不是流水线父子关系。
- 钟：`~/chief-clock/` + launchd `com.pojian.chief-clock`（:10/:25/:40/:50）只观察 + WARNING，不自动修手。

## 本机路径
- Julius: `/Users/pojian/repos/julius`
- Director: `/Users/pojian/repos/director`
- Control plane: `/Users/pojian/repos/director-control-plane`
- Clock: `/Users/pojian/chief-clock/`
- 交接报告: `director-control-plane/reports/CURRENT_STATE_REPORT_2026-08-20.md`

## 已交付（黄仁勋 · 手艺与信念 · v0.1）
J3→J7 曾 PASS；Owner 随后判定叙事入口错误并推翻重写成稿。

**当前权威成稿（可交付）：**
`/Users/pojian/repos/julius/script-drafts/黄仁勋·手艺与信念.md`
（已同步到交付包 `exports/deliverables/huang-renxun-craft-belief/script/draft.md`）

叙事决议（Owner）：
- 入口：先制造问题（2006 奇怪决定 / 投资人会觉得疯），不是金句、不是默认观众已认识黄仁勋。
- CUDA 延后白话解释；戏剧冲突 = 卖游戏显卡的公司用利润培育当时几乎不存在的市场。
- 母题：证据不足时愿意承担多少错误成本（不是「坚持二十年」鸡汤）。
- E8「深思熟虑」金句后置，不作片头。
- 不用 ChatGPT/2022 等证据池外钩子。

**交付包（文件齐，但下游视觉仍可能按旧叙事）：**
`/Users/pojian/repos/julius/exports/deliverables/huang-renxun-craft-belief/`
含：script/ · knowledge-map/ · frames/ · jianying-draft/ · delivery_manifest.json
`platform_upload: false`（未发平台）

对比稿（非主链，仅参考）：
`julius/script-drafts/opus-4.6/黄仁勋·手艺与信念.md`（OpenRouter opus-4.6；时间线型，已否为主稿）

## 现场快照（Executor 11:00 采样；接管时请复采）
- Julius: PASS · J7 · idle（`:25`）
- Director: 生产在跑；`GET :8000/health` 200 `commit=dirty`；只观察（`:10`）
- Control plane: `main` @ `7720608`（WRAP-001 已合 PR#2）；idle
- Clock: on_time；alerts none
- Git：三仓工作区均脏；Julius exports/脚本多未入库；Director ahead 14 脏热树=生产

## 已知缺口（接管后优先确认）
1. **成稿已重写，J4 地图 / J5 帧 / J6 剪映仍是旧入口叙事** → 是否授权整链重跑 J4→J7，Need approval。
2. 成稿 / exports 是否入库 git → Need approval（勿私自 push）。
3. Status Contract v1 采纳、D-EVOL 开哪一条、J-POS → QUEUED，等点名。
4. 「2006」「存在性威胁」等风险项见成稿文末「风险与待核」。

## 你接手后第一小时建议
1. 读 `CURRENT_STATE_REPORT_2026-08-20.md` + 打开权威成稿通读一遍。
2. 复采三份 `HOURLY_STATUS.md` + `~/chief-clock/status/LATEST.md` + `/health`。
3. 问 Owner 一句：是否授权按新成稿重跑 J4→J7（更新地图/帧/剪映并重打交付包）？还是只交付文稿、视觉以后再动？
4. 未获授权：不 hy3、不发平台、不装 Agent Runner、不改 Director 业务。

## 成功标准（本交接）
- Codex 能独立说清：交付物在哪、成稿决议是什么、什么已冻、下一步只缺 Owner 哪一句。
- 不把临时 Executor 的建议当成已批准架构。
```

---

## 给 Owner 的一句话

粘贴区已含全部上下文。接管窗读完后，你只需答一句：  
**「按新成稿重跑 J4→J7」** 或 **「只交文稿，视觉不动」**。
