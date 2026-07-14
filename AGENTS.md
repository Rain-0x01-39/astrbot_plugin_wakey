# wakey — 智能体指令

AstrBot 插件：用小模型 (0.5B+) 做 PASS/IGNORE 二值判断，控制主 LLM 是否回复。

## 架构

- **单文件**：`main.py`（约 245 行）。所有逻辑在 `WakeyPlugin(star.Star)` 中。
- 无依赖、无构建步骤、无测试、无 lint 配置。
- 同级插件（`Astrbot_plugin_Heartflow`、`astrbot_plugin_wakepro`）共享父目录但彼此独立。

## AstrBot 插件 API（非显而易见的要点）

- `Star.__init__(self, context: star.Context, config)` — `config` 是类字典对象，用 `config.get("key", default)` 取值。
- `provider.text_chat(prompt=..., contexts=[])` — 系统提示嵌入在 `prompt` 字符串中；没有单独的 `system_prompt` 参数。
- `event.unified_msg_origin` — 每个群聊会话的唯一标识，用作 buffer 字典的 key。
- `event.is_at_or_wake_command = True` — 触发主 LLM 回复（"唤醒"机制）。
- `event.stop_event()` — 完全阻止消息（被动 IGNORE 时使用）。
- hook 优先级设为极低（此处为 -114514），确保命令 handler（默认 priority=0）先匹配执行，wakey 最后兜底处理未被命令匹配的消息。主动路径设置 `is_at_or_wake_command` 仍在 LLM 调度之前生效，被动路径的 `stop_event()` 只对无命令匹配的假命令生效。

## Judge 输出格式（关键）

Judge 模型输出**纯文本**，不是 JSON：

```
原因一句话
PASS
```

解析逻辑（在 `_call_judge` 中）：
1. 按换行 split，取最后一行非空行作为结论
2. `verdict.upper().rstrip("。.!！,.，")` 然后 `startswith("PASS")` 或 `startswith("IGNOR")` — `startswith` 容忍额外文本
3. 第一行用作人类可读的原因（记录日志）
4. 格式不匹配时重试两次

## 配置

`_conf_schema.json` 中三个配置项。`judge_provider` 使用 `"_special": "select_provider"` 以在 WebUI 中显示 provider 选择器。

- `judge_provider`（string，`""`）— 为空则插件跳过所有处理
- `context_count`（int，`10`）
- `passive_judge`（bool，`true`）

## 关键行为

- **主动路径**：消息未 @ bot → judge 判断 PASS/IGNORE → 若 PASS，设置 `is_at_or_wake_command = True` + 在系统提示中注入"非正式参与"说明
- **被动路径**：消息已 @ 或唤醒命令 → 若 `passive_judge` 启用，judge 过滤噪音（纯@无内容、刷屏等）→ IGNORE 调用 `stop_event()`；PASS 放行正常流程
- **Buffer**：每个会话一个 deque，存储 `{name, text, bot}` 字典。Bot 自身的回复通过 `after_message_sent` hook 记录。`exclude_last` 防止当前消息出现在它自己的 judge 上下文中。
- **命令**：`/wakey`（状态）、`/wakey_test <msg>`（干跑 judge，消息前加 `@` 测试被动判断）、`/wakey_reset`（清空缓冲区）
