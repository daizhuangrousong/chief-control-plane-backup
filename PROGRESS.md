# PROGRESS · CURSOR-RUNNER R1 BOOTSTRAP

- 目标：接入官方 Cursor CLI，完成一次低风险真实试跑，验证飞书出站，通过后建立仅面向 Control Plane 的本机常驻 Runner。停在 Chief REVIEW。
- Owner approval：`OWNER-APPROVAL-20260820-CURSOR-R1-BOOTSTRAP`
- 工作树：`/Users/pojian/repos/director-control-plane-r1-bootstrap` 分支 `cursor-runner-r1-bootstrap`
- 阶段：代码与反向门禁完成；真实 pilot 与飞书出站独立 BLOCKED；LaunchAgent 未启用；待 Chief REVIEW
- 任务 0：91 tests / 0 fail / 0 skip；HEAD=R0 `fe5062fa75691ba366d209aac1f927f0e29ad643`
- 最终测试：103 tests / 0 fail / 0 skip；`git diff --check` 通过
- 真实 Cursor `--print` 调用次数：0
- 飞书测试卡：0
- LaunchAgent label：未启用（模板 `com.pojian.chief-cursor-runner`）
- 日志路径：未启用（预定 `var/logs/chief-cursor-runner.log`）
- Pilot task/lease/review id：无（未发起真实调用）
- 最大风险：在未认证时误发 `--print` 或把凭据写入 plist。已 fail closed。
