from collections import deque

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import Provider
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr


class WakeyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.judge_provider = config.get("judge_provider", "")
        self.context_count = config.get("context_count", 10)
        self.passive_judge = config.get("passive_judge", True)
        self.group_whitelist = config.get("group_whitelist", [])
        self._buffer: dict[str, deque] = {}
        self._buffer_max = max(self.context_count * 4, 40)
        logger.info(
            f"[wakey] init | provider={self.judge_provider} | "
            f"context={self.context_count} | passive={self.passive_judge}"
        )

    # ==================== buffer ====================

    def _record(self, event: AstrMessageEvent, *, is_bot: bool = False):
        umo = event.unified_msg_origin
        if umo not in self._buffer:
            self._buffer[umo] = deque(maxlen=self._buffer_max)
        self._buffer[umo].append(
            {
                "name": event.get_sender_name(),
                "text": event.message_str,
                "bot": is_bot,
            }
        )

    def _get_context(self, umo: str, exclude_last: str | None = None) -> str:
        msgs = list(self._buffer.get(umo, []))
        if exclude_last and msgs and msgs[-1]["text"] == exclude_last:
            msgs = msgs[:-1]
        recent = msgs[-self.context_count :]
        if not recent:
            return "暂无聊天记录"
        lines = []
        for m in recent:
            prefix = "- bot" if m["bot"] else f"- {m['name']}"
            lines.append(f"{prefix}: {m['text']}")
        return "\n".join(lines)

    # ==================== judge ====================

    _ACTIVE_SYSTEM = """你是一个群聊助手。根据聊天上下文判断是否应该回应。

以下情况应回复(PASS)：
- 消息提到你的名字或昵称
- 讨论你感兴趣或擅长的话题
- 是当前话题的自然延续，即使没有直接@你
- 群友在求助、提问、或需要回应

以下情况应忽略(IGNORE)：
- 无意义内容（纯表情、单字、刷屏）
- 与当前话题无关的闲聊，且没有@你
- 看起来像命令或误触发的机器人指令
- 群友之间互相对话，与你无关

重要：默认保守策略——不确定时输出 IGNORE。宁可沉默也不要冒昧插话。"""

    _PASSIVE_SYSTEM = """你是一个群聊助手。有人正在召唤你(@你或叫你名字)。判断是否应该回应。

以下情况应回应(PASS)：
- 召唤有实质内容（提问、求助、讨论等）
- 是延续之前的话题

以下情况应忽略(IGNORE)：
- 纯@无实质内容
- 刷屏召唤
- 无意义表情包或单字

重要：默认保守策略——不确定时输出 IGNORE。宁可沉默也不要冒昧插话。"""

    async def _call_judge(self, system: str, user: str) -> tuple[bool, str]:
        """Call the small judge model and parse PASS/IGNORE verdict."""
        provider = self.context.get_provider_by_id(self.judge_provider)
        if not isinstance(provider, Provider):
            return False, "judge_provider 未配置"

        full_prompt = (
            f"{system}\n\n"
            f"---\n"
            f"{user}\n"
            f"---\n"
            f"按以下格式输出：\n"
            f"第一行：判断理由\n"
            f"第二行：IGNORE 或 PASS"
        )

        for attempt in range(2):
            try:
                resp = await provider.text_chat(prompt=full_prompt, contexts=[])
                text = resp.completion_text.strip()
                logger.debug(f"[wakey] judge原始输出 (尝试{attempt + 1}):\n{text}")
                ok, reason = self._parse_verdict(text)
                if ok is not None:
                    return ok, reason
                logger.info(f"[wakey] 非预期判断输出 (尝试{attempt + 1}): {text[:300]}")
            except Exception as e:
                logger.error(f"[wakey] judge异常 (尝试{attempt + 1}): {e}")
        return False, "解析失败"

    @staticmethod
    def _parse_verdict(text: str) -> tuple[bool | None, str]:
        """Parse judge output. Returns (ok, reason) or (None, "") if unparseable."""
        lines = [
            line.strip() for line in text.split("\n") if line.strip(".。,，!！:：- ")
        ]
        if not lines:
            return None, ""

        reason = lines[0].rstrip(".。,，!！:：- ")
        text_upper = text.upper()

        # 查找最后一个 PASS 和 IGNOR 的位置
        last_pass = text_upper.rfind("PASS")
        last_ignor = text_upper.rfind("IGNOR")

        # 都没找到
        if last_pass == -1 and last_ignor == -1:
            return None, ""

        # 只找到一个
        if last_ignor == -1:
            return True, reason
        if last_pass == -1:
            return False, reason

        # 都找到，比较位置（最后一个优先）
        if last_pass > last_ignor:
            return True, reason
        else:
            return False, reason

    async def _judge_active(self, event: AstrMessageEvent) -> tuple[bool, str]:
        ctx = self._get_context(
            event.unified_msg_origin, exclude_last=event.message_str
        )
        user = (
            f"最近聊天记录：\n{ctx}\n\n"
            f"最新消息 (来自 {event.get_sender_name()}): {event.message_str}"
        )
        return await self._call_judge(self._ACTIVE_SYSTEM, user)

    async def _judge_passive(self, event: AstrMessageEvent) -> tuple[bool, str]:
        ctx = self._get_context(
            event.unified_msg_origin, exclude_last=event.message_str
        )
        user = (
            f"最近聊天记录：\n{ctx}\n\n"
            f"有人召唤你 (来自 {event.get_sender_name()}): {event.message_str}"
        )
        return await self._call_judge(self._PASSIVE_SYSTEM, user)

    # ==================== hooks ====================

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=-114514)
    async def on_group_message(self, event: AstrMessageEvent):
        if event.get_sender_id() == event.get_self_id():
            return
        if not self.judge_provider:
            return

        if (
            self.group_whitelist
            and event.unified_msg_origin not in self.group_whitelist
        ):
            return

        self._record(event, is_bot=False)

        try:
            if event.is_at_or_wake_command:
                if not self.passive_judge:
                    return
                ok, reason = await self._judge_passive(event)
                event.set_extra("wakey_reason", reason)
                if ok:
                    logger.info(f"[wakey] 被动 PASS | {reason}")
                else:
                    logger.info(f"[wakey] 被动 IGNORE | {reason}")
                    event.stop_event()
                return

            ok, reason = await self._judge_active(event)
            event.set_extra("wakey_reason", reason)
            if ok:
                event.is_at_or_wake_command = True
                event.set_extra("wakey_triggered", True)
                logger.info(f"[wakey] 主动 PASS | {reason}")
            else:
                logger.debug(f"[wakey] 主动 IGNORE | {reason}")
        except Exception:
            logger.exception("[wakey] on_group_message异常")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        if not event.get_extra("wakey_triggered"):
            return
        if req and hasattr(req, "system_prompt"):
            note = (
                "（注意：本次是你主动参与群聊的，不是用户叫你。"
                "回复应自然随意，像普通群成员一样加入话题。）"
            )
            req.system_prompt = (req.system_prompt or "") + "\n" + note

    @filter.after_message_sent()
    async def on_after_message_sent(self, event: AstrMessageEvent):
        result = event.get_result()
        if not result or not result.chain:
            return
        reply = "".join(c.text for c in result.chain if isinstance(c, Plain)).strip()
        if reply:
            self._record(event, is_bot=True)

    # ==================== commands ====================

    @filter.command_group("wakey")
    def wakey():
        """wakey 插件控制"""
        pass

    @wakey.command("status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看 wakey 状态"""
        umo = event.unified_msg_origin
        buf_size = len(self._buffer.get(umo, []))
        yield event.plain_result(
            f"wakey v1.0.0\n"
            f"judge_provider: {self.judge_provider or '未配置'}\n"
            f"context_count: {self.context_count}\n"
            f"passive_judge: {self.passive_judge}\n"
            f"当前会话缓存: {buf_size}条"
        )

    @wakey.command("test")
    async def cmd_test(self, event: AstrMessageEvent, message: GreedyStr):
        """测试 judge 判断"""
        message = (message or "").strip()
        if not message:
            yield event.plain_result("用法：/wakey test <消息内容>")
            return
        if not self.judge_provider:
            yield event.plain_result("未配置 judge_provider")
            return

        ctx = self._get_context(
            event.unified_msg_origin, exclude_last=event.message_str
        )
        if message.startswith("@"):
            system = self._PASSIVE_SYSTEM
            user = f"最近聊天记录：\n{ctx}\n\n有人召唤你 (来自 测试用户): {message}"
            mode = "被动"
        else:
            system = self._ACTIVE_SYSTEM
            user = f"最近聊天记录：\n{ctx}\n\n最新消息 (来自 测试用户): {message}"
            mode = "主动"

        ok, reason = await self._call_judge(system, user)
        verdict = "PASS" if ok else "IGNORE"
        yield event.plain_result(f"[{mode}] {verdict}\n原因: {reason}")

    @wakey.command("reset")
    async def cmd_reset(self, event: AstrMessageEvent):
        """重置当前会话的上下文缓存"""
        self._buffer.pop(event.unified_msg_origin, None)
        yield event.plain_result("当前会话上下文已重置。")

    async def terminate(self):
        self._buffer.clear()
