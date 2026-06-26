# LangBot Skill Authoring

LangBot Skill Authoring 是一个面向 LangBot 的 Skill 沉淀与生成插件，用于把运行记录、QA 证据、排障笔记、用户反馈和完成后的对话回合转换成可审核的 `SKILL.md` 草稿。

它不是 LangBot Skill 运行时的替代品。LangBot 仍然负责 Skill 的发现、激活、挂载和执行；本插件补的是注册前的沉淀流程：

```text
来源证据 -> 候选 Skill -> 风险报告 -> 审核 -> 导出 / 发布包
```

在个人助手场景中，也可以开启受控的自动沉淀模式：

```text
来源证据或已完成回合
  -> 自动候选 -> 风险报告 -> 策略门禁 -> 可选自动审核 / 导出
```

自动沉淀由 `auto_deposition_enabled` 总开关控制，默认关闭。

## 运行时边界

本插件不会改变 LangBot 如何发现、激活、挂载或运行 Skill。运行时仍由 LangBot Core 负责：

- Agent 可以在 `/workspace` 下创建 Skill 包，并调用内置 `register_skill` 工具。
- 管理员可以继续通过 LangBot 现有 `/api/v1/skills` 接口管理 Skill。
- 已激活 Skill 仍然使用 LangBot 现有 sandbox 和权限检查。

本插件负责的是注册前的产品工作流：判断什么值得沉淀、生成结构化草稿、扫描 secrets 和环境耦合风险、记录审核与验证证据、导出可注册的 Skill 包。

## 自动沉淀模式

自动沉淀面向个人助手场景：用户希望助手从已确认的对话、重复流程或排障经验中“一键学习”。

开启后，页面里的 `One-click Deposit` 动作和 `skill_auto_deposit` 工具会：

1. 从输入证据创建候选 Skill。
2. 生成结构化 Skill 草稿。
3. 执行确定性风险扫描。
4. 应用配置的风险策略。
5. 在允许时自动记录审核并导出包。

该模式仍然不会直接写入运行时 Skill 注册表。返回结果包含 `register_skill_hint`，供 Agent 将包写入 `/workspace/<skill-name>` 后，再调用 LangBot 内置 `register_skill` 工具。

插件也可以从 LangBot 已完成回合中被动学习。当同时开启 `auto_deposition_enabled` 和 `post_response_candidate_enabled` 时，EventListener 会监听 `NormalMessageResponded`，读取当前 `user_message_text`、助手 `response_text`、函数调用名和可用 query vars。只有在确定性置信度较高，或用户明确说出“沉淀一下”“记住这个流程”“make this a skill”等表达时，才会创建候选 Skill。

回复后沉淀保持保守：

- 默认关闭
- 默认只在私聊 / 个人助手场景生效
- 默认只创建候选，不自动导出
- 可选自动导出仍受 `auto_deposition_policy` 限制
- 不会自动执行运行时 `register_skill`
- 不会自动写入 LongTermMemory

相关配置：

- `auto_deposition_enabled`：自动沉淀总开关，默认 `false`
- `auto_deposition_policy`：自动沉淀风险策略，支持 `pass_only`、`allow_warn`、`allow_blocked`
- `auto_deposition_reviewer`：自动审核记录中的 reviewer 标签
- `post_response_candidate_enabled`：启用回复后候选沉淀，默认 `false`
- `post_response_auto_export`：允许回复后候选自动审核并导出，默认 `false`
- `post_response_private_only`：仅私聊生效，默认 `true`
- `post_response_min_confidence`：创建候选所需最低置信度，默认 `0.72`
- `post_response_max_source_chars`：复制到候选来源中的最大字符数，默认 `6000`
- `post_response_explicit_only`：仅响应明确沉淀指令，默认 `false`

自动沉淀会明确披露风险与消耗：

- 风险：把一次性流程过度泛化、保存私人上下文、泄露 secrets 或本地路径、把 prompt injection 文本长期保存为指令。
- 消耗：来源字符数、插件存储写入、可选包导出写入、运行时变更，以及是否调用 LLM。当前确定性 MVP 不产生 LLM 调用。

## 生命周期与淘汰

Hermes 风格的学习不只是写入，还需要来源、治理和可恢复的遗忘。本插件为沉淀候选维护轻量生命周期：

```text
candidate -> active -> deprecated -> archived
                  \-> superseded
```

每个候选都会携带 provenance 元数据：

- `origin`：例如 `manual`、`auto_deposition`、`agent_review`、`imported`、`runtime_registered`
- `protected`：受保护候选不能被 deprecated、archived 或 superseded，除非显式传入 `force=true`
- `auto_curation_eligible`：标记该候选未来可被自动治理流程处理

可以通过 `skill_lifecycle_manage` 工具或页面 API 记录生命周期事件：

- 正向信号：`used`、`success`、`positive_feedback`、`eval_pass`
- 负向信号：`failure`、`negative_feedback`、`eval_fail`、`stale`、`security_issue`、`memory_conflict`、`superseded`

保留策略会计算分数并建议 `keep`、`deprecate`、`archive` 或 `superseded`。报告中的 `auto_apply_allowed` 用于区分未来是否适合自动执行。当前插件只修改自身治理记录；删除、隐藏或恢复运行时 Skill 仍需要 LangBot 现有 Skill 管理能力或未来的 admin proxy。

导出的包包含：

- `SKILL.md`
- `references/source-excerpt.md`
- `references/risk-report.json`
- `references/provenance.json`
- `references/learning-decision.json`
- `references/support-files.json`

这种设计会把会话特定细节放到 support files 中，避免把一次性运行记录直接固化成过窄的 Skill。

## 与 LongTermMemory 协同

建议把 LongTermMemory 和 Skill Authoring 作为不同资产层使用：

- LongTermMemory L1：稳定画像事实和偏好
- LongTermMemory L2：情景记忆、决策、事件和纠正历史
- Skill Authoring：需要工具、步骤、约束和验证的可复用流程

`skill_lifecycle_manage` 支持 `memory_plan`，可判断来源更适合成为 Skill、L1 profile 更新、L2 episodic memory，还是需要人工审核。当两者都适用时，建议把可执行流程保留为 Skill，只把简短来源或使用摘要写入 L2。

插件会返回机器可读的 `learning-decision/v1` 对象和可选 LongTermMemory 工具建议。本插件不会直接调用 LongTermMemory；Agent 或未来 host 级 workflow 可在用户审核后执行建议的 `update_profile` 或 `remember`。

如果安装了 LongTermMemory，回复后沉淀会在可用时记录 `_ltm_context` 的摘要作为 provenance，帮助 reviewer 理解 session / speaker 背景，同时避免两个插件直接耦合或重复写记忆。

## Hermes 对齐状态

本插件已经实现：

- 带风险 / 消耗披露的一键沉淀
- 基于 `NormalMessageResponded` 的 LangBot-native 回复后候选沉淀
- provenance、保护标记和自动治理资格
- 可恢复 archive / deprecate / supersede 的生命周期评分
- 带 support files manifest 的导出包
- 与 LongTermMemory 协同的 `learning-decision/v1`

本插件内部没有实现：

- Hermes 那种完整对话后台 fork 审核
- prompt-cache-aware 的辅助模型路由
- 当前事件 / query vars 之外的完整 tool result trace 审核
- 直接运行时 Skill archive / delete / restore
- 跨所有已安装运行时 Skill 的自动 umbrella consolidation

这些能力需要更稳定的 LangBot host API：更完整的运行 trace、跨插件调用、运行时 Skill provenance、可恢复 runtime archive / restore。它们不是当前候选沉淀闭环的前置条件。

后续 pipeline 重构计划见 `docs/pipeline-host-integration-plan.md`。

## 当前可用能力

- 候选、审核、验证、导出的 Page 后端 API
- 面向管理员的 Page UI
- LLM 可调用工具：
  - `skill_auto_deposit`
  - `skill_lifecycle_manage`
  - `skill_candidate_create`
  - `skill_candidate_risk_check`
  - `skill_candidate_export`
- 基于来源证据和风险说明的确定性 `SKILL.md` 生成
- LangBot 内运行时使用插件存储，测试和离线开发时使用内存 fallback

## 开发

```bash
python -m pytest
```

可用 LangBot plugin SDK CLI 构建：

```bash
lbp build
```

在 LangBot 中运行时，Agent 仍然可以把导出的包写入 `/workspace`，再使用内置 `register_skill` 工具创建最终运行时 Skill。需要从审核页面直接发布的部署，也可以在未来扩展 Page 后端调用 `/api/v1/skills`。
