# wakey ✨

> [!WARNING]
> 早期开发阶段 — 包含大量 vibecoding 成分，未经良好测试。生产环境使用前请自行验证。

wakey wakey~ 用小模型智能判断 bot 该不该插话。单文件设计，轻量级判断，低成本。

## 设计理念

Heartflow 用 5 维加权打分来判断是否回复，权重很难调（模型 reasoning 说该回，但分数没过线）。  
wakey 直接让模型输出 **PASS 或 IGNORE**，更简单的判断方式。

```
消息 → 小模型判断 → PASS → 唤醒主 LLM 回复
                    → IGNORE → 跳过
```

## 核心功能

- **主动唤醒**：没人at时，小模型根据聊天上下文判断该不该插话
- **被动过滤**：被at时也过小模型，过滤纯 @/刷屏召唤/无意义内容
- **PASS/IGNORE 格式**：第一行原因，第二行判决，简洁直接
- **上下文缓冲**：每会话记录最近消息，传给 judge 模型参考
- **调试命令**：`/wakey` `/wakey_test` `/wakey_reset`

## 配置

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `judge_provider` | string | `""` | 小模型 provider 名，不配置则跳过所有处理 |
| `context_count` | int | `10` | 传给 judge 的上下文条数 |
| `passive_judge` | bool | `true` | 关闭后所有 @ 消息直接放行，不走 judge |

## 推荐模型

建议使用 8B+ 参数的模型，如 Qwen2.5-8B、Llama-3.1-8B 等。更小的模型格式稳定性较差，目前wakey有一定兜底能力。

## 使用

1. 加载插件，在 WebUI 中配置 `judge_provider` 指向你的小模型
2. 正常聊天，插件自动判断
3. `/wakey` 查看当前状态
4. `/wakey_test <消息>` 手动测试 judge
5. `/wakey_reset` 清空当前会话上下文

## TODO

> 仅 MVP 保留核心功能，以下按需推进。

- [ ] **bot 名字/身份注入**：judge prompt 中加入 bot 的名字和简短人设，提升"消息提到你的名字/讨论你擅长话题"的命中率
- [ ] **debouce 消息合并**：同用户短时间连续消息合并为一条再 judge，减少重复调用
- [ ] **关键词屏蔽/echo 检测**：硬拒绝某些消息（广告、复读），不浪费 judge 调用
- [ ] **能量系统**：回复消耗能量、跳过恢复能量、每日重置，防止刷屏
- [ ] **冷却间隔**：两次主动回复最小间隔配置
- [ ] **MentionStreak 旁路**：同用户短时间多次 at 自动放行
- [ ] **随机保底**：极小概率强行唤醒防死寂
- [ ] **人设摘要缓存**：用小模型压缩主 LLM 的系统提示词，注入 judge context
- [ ] **私聊支持**：当前仅支持群聊 (GROUP_MESSAGE)

## 致谢

设计过程中参考了以下优秀插件：

- [Astrbot_plugin_Heartflow](https://github.com/advent259141/Astrbot_plugin_Heartflow) — 双 LLM 架构、人设摘要缓存、能量系统的灵感来源
- [astrbot_plugin_wakepro](https://github.com/Zhalslar/astrbot_plugin_wakepro) — debounce 消息合并、关键词屏蔽、echo 检测的设计参考

## 许可证

MIT
