import datetime
import re
import time
from typing import Dict, List, Optional

# Discord mention patterns
_MENTION_USER = re.compile(r"<@!?(\d+)>")
_MENTION_ROLE = re.compile(r"<@&(\d+)>")
_MENTION_CHANNEL = re.compile(r"<#(\d+)>")
_MENTION_ALL = re.compile(r"<@&?(\d+)>|<#(\d+)>")


class DiscordConverter:
    """
    Discord 事件转换器

    将 Discord Gateway Dispatch 事件转换为 ErisPulse OneBot12 标准格式。

    核心原则：
    1. 严格兼容：所有标准字段遵循 OneBot12 规范
    2. 明确扩展：平台特有功能使用 discord_ 前缀
    3. 数据完整：原始事件数据保留在 discord_raw 字段
    4. 时间统一：所有时间戳转换为 10 位 Unix 时间戳（秒级）
    """

    # 消息类事件
    MESSAGE_EVENTS = {
        "MESSAGE_CREATE",
        "MESSAGE_UPDATE",
        "MESSAGE_DELETE",
        "MESSAGE_DELETE_BULK",
        "MESSAGE_REACTION_ADD",
        "MESSAGE_REACTION_REMOVE",
        "MESSAGE_REACTION_REMOVE_ALL",
        "MESSAGE_REACTION_REMOVE_EMOJI",
    }

    # 通知类事件
    NOTICE_EVENTS = {
        "GUILD_MEMBER_ADD",
        "GUILD_MEMBER_REMOVE",
        "GUILD_MEMBER_UPDATE",
        "GUILD_ROLE_CREATE",
        "GUILD_ROLE_DELETE",
        "GUILD_ROLE_UPDATE",
        "CHANNEL_CREATE",
        "CHANNEL_DELETE",
        "CHANNEL_UPDATE",
        "TYPING_START",
    }

    # 通知 detail_type 映射
    NOTICE_DETAIL_MAP = {
        "GUILD_MEMBER_ADD": "group_member_increase",
        "GUILD_MEMBER_REMOVE": "group_member_decrease",
        "GUILD_MEMBER_UPDATE": "group_member_update",
        "GUILD_ROLE_CREATE": "group_role_create",
        "GUILD_ROLE_DELETE": "group_role_delete",
        "GUILD_ROLE_UPDATE": "group_role_update",
        "CHANNEL_CREATE": "channel_create",
        "CHANNEL_DELETE": "channel_delete",
        "CHANNEL_UPDATE": "channel_update",
        "TYPING_START": "typing",
        "MESSAGE_DELETE": "group_message_delete",
        "MESSAGE_DELETE_BULK": "group_message_delete_bulk",
        "MESSAGE_REACTION_ADD": "group_message_reaction_add",
        "MESSAGE_REACTION_REMOVE": "group_message_reaction_remove",
    }

    def __init__(self):
        self.bot_id = ""

    def convert(self, raw_data: Dict, event_name: str) -> Optional[Dict]:
        """
        将 Discord Dispatch 事件转换为 OneBot12 标准格式

        :param raw_data: Discord Dispatch 的 d 字段（事件数据）
        :param event_name: Discord Dispatch 的 t 字段（事件名）
        :return: OneBot12 标准格式事件，不支持的事件返回 None
        """
        if not isinstance(raw_data, dict):
            return None

        event_type, detail_type = self._map_event_type(event_name, raw_data)

        base = self._create_base_event(raw_data, event_name, event_type, detail_type)

        handler = getattr(self, f"_handle_{event_name.lower()}", None)
        if handler:
            return handler(raw_data, base)

        # 通用处理：尝试提取用户信息
        self._fill_user_info(raw_data, base)
        return base

    # ==================== 基础事件构建 ====================

    def _create_base_event(
        self, raw_data: Dict, event_name: str, event_type: str, detail_type: str
    ) -> Dict:
        return {
            "id": self._generate_id(raw_data, event_name),
            "time": self._extract_time(raw_data),
            "type": event_type,
            "detail_type": detail_type,
            "platform": "discord",
            "self": {
                "platform": "discord",
                "user_id": self.bot_id,
            },
            "discord_raw": raw_data,
            "discord_raw_type": event_name,
        }

    def _map_event_type(self, event_name: str, raw_data: Dict) -> tuple:
        if event_name in self.MESSAGE_EVENTS:
            return "message", self._get_detail_type(raw_data)
        elif event_name == "INTERACTION_CREATE":
            return "request", "interaction"
        elif event_name in self.NOTICE_EVENTS:
            detail = self.NOTICE_DETAIL_MAP.get(event_name, event_name.lower())
            return "notice", detail
        elif event_name in ("READY", "RESUMED"):
            return "meta", event_name.lower()
        else:
            return "notice", event_name.lower()

    def _get_detail_type(self, raw_data: Dict) -> str:
        if "guild_id" in raw_data:
            return "channel"
        return "private"

    def _extract_time(self, raw_data: Dict) -> int:
        timestamp = raw_data.get("timestamp")
        if timestamp:
            try:
                dt = datetime.datetime.fromisoformat(
                    str(timestamp).replace("Z", "+00:00")
                )
                return int(dt.timestamp())
            except Exception:
                pass
        return int(time.time())

    def _generate_id(self, raw_data: Dict, event_name: str) -> str:
        msg_id = raw_data.get("id") or raw_data.get("message_id")
        if msg_id:
            return str(msg_id)
        return f"{event_name}_{int(time.time() * 1000)}"

    def _fill_user_info(self, raw_data: Dict, base: Dict):
        author = raw_data.get("author") or raw_data.get("user") or {}
        if author:
            base["user_id"] = str(author.get("id", ""))
            base["user_nickname"] = author.get("global_name") or author.get(
                "username", ""
            )

    # ==================== 消息事件处理 ====================

    def _handle_message_create(self, raw_data: Dict, base: Dict) -> Dict:
        author = raw_data.get("author", {})

        base["message_id"] = str(raw_data.get("id", ""))
        base["user_id"] = str(author.get("id", ""))
        base["user_nickname"] = author.get("global_name") or author.get("username", "")

        # 解析消息段
        segments = self._parse_message_content(raw_data)
        base["message"] = segments
        base["alt_message"] = self._generate_alt_message(segments)

        # 频道/服务器信息
        channel_id = str(raw_data.get("channel_id", ""))
        guild_id = raw_data.get("guild_id")

        base["channel_id"] = channel_id
        base["discord_channel_id"] = channel_id
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = channel_id
            base["target_id"] = channel_id
        else:
            base["group_id"] = channel_id
            base["target_id"] = base["user_id"]

        # 话题/Thread 支持
        if raw_data.get("thread"):
            thread = raw_data["thread"]
            if thread.get("id"):
                base["thread_id"] = str(thread["id"])

        # member 信息扩展
        member = raw_data.get("member")
        if member and isinstance(member, dict):
            base["discord_member"] = member
            if member.get("nick"):
                base["discord_member_nick"] = member["nick"]

        return base

    def _handle_message_update(self, raw_data: Dict, base: Dict) -> Dict:
        base["message_id"] = str(raw_data.get("id", ""))

        author = raw_data.get("author")
        if author:
            base["user_id"] = str(author.get("id", ""))
            base["user_nickname"] = author.get("global_name") or author.get(
                "username", ""
            )

        segments = self._parse_message_content(raw_data)
        base["message"] = segments
        base["alt_message"] = self._generate_alt_message(segments)

        channel_id = str(raw_data.get("channel_id", ""))
        guild_id = raw_data.get("guild_id")
        base["discord_channel_id"] = channel_id
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
        base["group_id"] = channel_id
        base["discord_edit_time"] = int(time.time())

        return base

    def _handle_message_delete(self, raw_data: Dict, base: Dict) -> Dict:
        base["message_id"] = str(raw_data.get("id", ""))
        channel_id = str(raw_data.get("channel_id", ""))
        guild_id = raw_data.get("guild_id")
        base["discord_channel_id"] = channel_id
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = channel_id
        else:
            base["detail_type"] = "private_message_delete"
        return base

    def _handle_message_delete_bulk(self, raw_data: Dict, base: Dict) -> Dict:
        ids = raw_data.get("ids", [])
        base["message_ids"] = [str(i) for i in ids]
        channel_id = str(raw_data.get("channel_id", ""))
        guild_id = raw_data.get("guild_id")
        base["discord_channel_id"] = channel_id
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = channel_id
        return base

    # ==================== 反应事件处理 ====================

    def _handle_message_reaction_add(self, raw_data: Dict, base: Dict) -> Dict:
        return self._fill_reaction_event(raw_data, base)

    def _handle_message_reaction_remove(self, raw_data: Dict, base: Dict) -> Dict:
        return self._fill_reaction_event(raw_data, base)

    def _fill_reaction_event(self, raw_data: Dict, base: Dict) -> Dict:
        base["message_id"] = str(raw_data.get("message_id", ""))
        user_id = raw_data.get("user_id")
        if user_id:
            base["user_id"] = str(user_id)
        channel_id = str(raw_data.get("channel_id", ""))
        guild_id = raw_data.get("guild_id")
        base["discord_channel_id"] = channel_id
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = channel_id
        emoji = raw_data.get("emoji", {})
        if emoji:
            base["discord_emoji"] = emoji
        return base

    # ==================== 通知事件处理 ====================

    def _handle_guild_member_add(self, raw_data: Dict, base: Dict) -> Dict:
        user = raw_data.get("user", {})
        base["user_id"] = str(user.get("id", ""))
        base["user_nickname"] = user.get("global_name") or user.get("username", "")
        guild_id = raw_data.get("guild_id")
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = str(guild_id)
        return base

    def _handle_guild_member_remove(self, raw_data: Dict, base: Dict) -> Dict:
        user = raw_data.get("user", {})
        base["user_id"] = str(user.get("id", ""))
        base["user_nickname"] = user.get("global_name") or user.get("username", "")
        guild_id = raw_data.get("guild_id")
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = str(guild_id)
        return base

    def _handle_guild_member_update(self, raw_data: Dict, base: Dict) -> Dict:
        user = raw_data.get("user", {})
        base["user_id"] = str(user.get("id", ""))
        base["user_nickname"] = user.get("global_name") or user.get("username", "")
        guild_id = raw_data.get("guild_id")
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = str(guild_id)
        return base

    def _handle_guild_role_create(self, raw_data: Dict, base: Dict) -> Dict:
        guild_id = raw_data.get("guild_id")
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = str(guild_id)
        role = raw_data.get("role", {})
        if role:
            base["discord_role"] = role
        return base

    def _handle_guild_role_delete(self, raw_data: Dict, base: Dict) -> Dict:
        guild_id = raw_data.get("guild_id")
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = str(guild_id)
        role_id = raw_data.get("role_id")
        if role_id:
            base["discord_role_id"] = str(role_id)
        return base

    def _handle_guild_role_update(self, raw_data: Dict, base: Dict) -> Dict:
        return self._handle_guild_role_create(raw_data, base)

    def _handle_channel_create(self, raw_data: Dict, base: Dict) -> Dict:
        base["discord_channel"] = raw_data
        guild_id = raw_data.get("guild_id")
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
        channel_id = raw_data.get("id")
        if channel_id:
            base["discord_channel_id"] = str(channel_id)
        return base

    def _handle_channel_delete(self, raw_data: Dict, base: Dict) -> Dict:
        return self._handle_channel_create(raw_data, base)

    def _handle_channel_update(self, raw_data: Dict, base: Dict) -> Dict:
        return self._handle_channel_create(raw_data, base)

    def _handle_typing_start(self, raw_data: Dict, base: Dict) -> Dict:
        user_id = raw_data.get("user_id")
        if user_id:
            base["user_id"] = str(user_id)
        channel_id = str(raw_data.get("channel_id", ""))
        guild_id = raw_data.get("guild_id")
        base["discord_channel_id"] = channel_id
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = channel_id
        return base

    # ==================== 交互事件处理 ====================

    def _handle_interaction_create(self, raw_data: Dict, base: Dict) -> Dict:
        user = raw_data.get("user") or raw_data.get("member", {}).get("user", {})
        if user:
            base["user_id"] = str(user.get("id", ""))
            base["user_nickname"] = user.get("global_name") or user.get("username", "")
        channel_id = str(raw_data.get("channel_id", ""))
        guild_id = raw_data.get("guild_id")
        base["discord_channel_id"] = channel_id
        if guild_id:
            base["discord_guild_id"] = str(guild_id)
            base["group_id"] = channel_id
        base["discord_interaction"] = raw_data
        return base

    # ==================== 消息内容解析 ====================

    def _parse_message_content(self, raw_data: Dict) -> List[Dict]:
        segments = []

        content = raw_data.get("content") or ""
        if content:
            segments.extend(self._parse_text_with_mentions(content, raw_data))

        # Embeds
        for embed in raw_data.get("embeds", []):
            segments.append(
                {
                    "type": "discord_embed",
                    "data": {"embed": embed},
                }
            )

        # Attachments
        for attachment in raw_data.get("attachments", []):
            url = attachment.get("url", "")
            filename = attachment.get("filename", "")
            content_type = attachment.get("content_type", "")
            seg_type = "file"
            if content_type.startswith("image"):
                seg_type = "image"
            elif content_type.startswith("video"):
                seg_type = "video"
            elif content_type.startswith("audio"):
                seg_type = "audio"
            segments.append(
                {
                    "type": seg_type,
                    "data": {
                        "file": url,
                        "file_id": attachment.get("id", ""),
                        "file_name": filename,
                        "url": url,
                        "content_type": content_type,
                    },
                }
            )

        # Stickers
        for sticker in raw_data.get("sticker_items", []):
            segments.append(
                {
                    "type": "discord_sticker",
                    "data": sticker,
                }
            )

        # Components (buttons, selects)
        components = raw_data.get("components")
        if components:
            segments.append(
                {
                    "type": "discord_components",
                    "data": {"components": components},
                }
            )

        if not segments:
            segments.append({"type": "text", "data": {"text": ""}})

        return segments

    def _parse_text_with_mentions(self, content: str, raw_data: Dict) -> List[Dict]:
        """解析 Discord 文本内容，将 mention 格式转换为 mention 消息段"""
        segments = []

        user_mentions = {}
        for m in raw_data.get("mentions", []):
            uid = m.get("id", "")
            if uid:
                user_mentions[uid] = m

        # 合并所有 mention 模式
        pattern = re.compile(r"<@!?(\d+)>|<@&(\d+)>|<#(\d+)>")

        last_end = 0
        for match in pattern.finditer(content):
            start, end = match.span()

            if start > last_end:
                text = content[last_end:start]
                if text:
                    segments.append({"type": "text", "data": {"text": text}})

            user_id = match.group(1)
            role_id = match.group(2)
            channel_ref_id = match.group(3)

            if user_id:
                user_info = user_mentions.get(user_id, {})
                segments.append(
                    {
                        "type": "mention",
                        "data": {
                            "user_id": user_id,
                            "user_nickname": (
                                user_info.get("global_name")
                                or user_info.get("username", "")
                            ),
                        },
                    }
                )
            elif role_id:
                segments.append(
                    {
                        "type": "discord_role_mention",
                        "data": {"role_id": role_id},
                    }
                )
            elif channel_ref_id:
                segments.append(
                    {
                        "type": "discord_channel_mention",
                        "data": {"channel_id": channel_ref_id},
                    }
                )

            last_end = end

        if last_end < len(content):
            text = content[last_end:]
            if text:
                segments.append({"type": "text", "data": {"text": text}})

        if not segments and content:
            segments.append({"type": "text", "data": {"text": content}})

        return segments

    def _generate_alt_message(self, segments: List[Dict]) -> str:
        parts = []
        for seg in segments:
            t = seg.get("type", "")
            d = seg.get("data", {})
            if t == "text":
                parts.append(d.get("text", ""))
            elif t == "mention":
                parts.append(f"@{d.get('user_nickname', d.get('user_id', ''))}")
            elif t == "mention_all":
                parts.append("@everyone")
            elif t == "discord_role_mention":
                parts.append(f"@&{d.get('role_id', '')}")
            elif t == "discord_channel_mention":
                parts.append(f"#{d.get('channel_id', '')}")
            elif t == "image":
                parts.append("[图片]")
            elif t == "video":
                parts.append("[视频]")
            elif t == "audio":
                parts.append("[语音]")
            elif t == "file":
                parts.append(f"[文件:{d.get('file_name', '')}]")
            elif t == "discord_embed":
                parts.append("[嵌入消息]")
            elif t == "discord_sticker":
                parts.append("[贴纸]")
            elif t == "discord_components":
                parts.append("[组件]")
        return "".join(parts)
