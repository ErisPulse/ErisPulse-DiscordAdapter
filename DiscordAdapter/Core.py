import asyncio
import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from ErisPulse.Core import client
from ErisPulse.Core.Bases.adapter import BaseAdapter
from ErisPulse.Core.Bases.websocket import WSMessage
from ErisPulse.Core.Event import register_event_mixin, unregister_platform_event_methods
from ErisPulse.runtime.config_schema import BotAccountConfig

from .Converter import DiscordConverter

# Gateway Intents
INTENT_GUILDS = 1 << 0
INTENT_GUILD_MEMBERS = 1 << 1
INTENT_GUILD_MESSAGES = 1 << 9
INTENT_MESSAGE_CONTENT = 1 << 15
DEFAULT_INTENTS = (
    INTENT_GUILDS | INTENT_GUILD_MESSAGES | INTENT_MESSAGE_CONTENT
)  # 33281

# Discord Gateway Opcodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

API_BASE = "https://discord.com/api/v10"


@dataclass
class DiscordAccountConfig(BotAccountConfig):
    token: str = field(
        default="",
        metadata={
            "description": "Discord Bot Token",
            "required": True,
            "secret": True,
            "webui": {"widget": "password", "group": "basic", "order": 2},
        },
    )
    intents: int = field(
        default=DEFAULT_INTENTS,
        metadata={
            "description": "Gateway Intents 位掩码（默认 GUILDS|GUILD_MESSAGES|MESSAGE_CONTENT = 33281）",
            "required": False,
            "webui": {"widget": "number", "group": "advanced", "order": 3},
        },
    )


class DiscordEventMixin:
    """Discord 平台事件扩展方法"""

    def get_channel_id(self) -> str:
        return self.get("discord_channel_id", "")

    def get_guild_id(self) -> str:
        return self.get("discord_guild_id", "")

    def get_username(self) -> str:
        return self.get("user_nickname", "")

    def get_global_name(self) -> str:
        raw = self.get("discord_raw", {})
        author = raw.get("author", {}) or raw.get("user", {})
        return author.get("global_name", "") or author.get("username", "")

    def is_dm(self) -> bool:
        return self.get("detail_type") == "private"

    def get_embeds(self) -> list:
        embeds = []
        for seg in self.get("message", []):
            if seg.get("type") == "discord_embed":
                embed = seg.get("data", {}).get("embed")
                if embed:
                    embeds.append(embed)
        return embeds

    def get_attachments(self) -> list:
        result = []
        for seg in self.get("message", []):
            if seg.get("type") in ("image", "file", "video", "audio"):
                result.append(seg.get("data", {}))
        return result

    def get_interaction_data(self) -> dict:
        return self.get("discord_interaction", {})


register_event_mixin("discord", DiscordEventMixin)


class DiscordAdapter(BaseAdapter):
    """Discord 适配器，支持多账户 Gateway WebSocket + REST API"""

    AccountConfigClass = DiscordAccountConfig

    class Send(BaseAdapter.Send):
        def __init__(self, adapter, target_type=None, target_id=None, account_id=None):
            super().__init__(adapter, target_type, target_id, account_id)

        def Text(self, text: str):
            return self.Raw_ob12([{"type": "text", "data": {"text": text}}])

        def Embed(self, embeds: Union[dict, list]):
            if isinstance(embeds, dict):
                return self.Raw_ob12(
                    [
                        {"type": "discord_embed", "data": {"embed": embeds}},
                    ]
                )
            else:
                return self.Raw_ob12(
                    [{"type": "discord_embed", "data": {"embed": e}} for e in embeds]
                )

        def Image(
            self,
            file: Union[str, bytes],
            filename: str = "image.png",
            caption: str = "",
        ):
            if isinstance(file, bytes):
                return self.Raw_ob12(
                    [
                        {
                            "type": "image",
                            "data": {"file": file, "file_name": filename},
                        },
                    ]
                )
            else:
                embed: dict = {"image": {"url": file}}
                if caption:
                    embed["description"] = caption
                return self.Embed(embed)

        def File(self, file: Union[str, bytes], filename: str = ""):
            if isinstance(file, bytes):
                return self.Raw_ob12(
                    [
                        {
                            "type": "file",
                            "data": {"file": file, "file_name": filename or "file"},
                        },
                    ]
                )
            else:
                return self.Raw_ob12(
                    [
                        {
                            "type": "file",
                            "data": {"file": file, "file_name": filename or "file"},
                        },
                    ]
                )

        def Reply(
            self,
            content: Union[str, list, None] = None,
            message_id: Union[str, int, None] = None,
        ):
            """
            回复消息。支持两种调用方式：
            - Reply(message_id): 链式修饰，返回 self
            - Reply(content, message_id): 一步发送回复
            """
            # 链式修饰模式：Reply(message_id)
            if content is not None and message_id is None:
                self._reply_message_id = content
                return self

            # 终端发送模式：Reply(content, message_id)
            if isinstance(content, str):
                content = [{"type": "text", "data": {"text": content}}]

            ctx = self.send_context

            async def _send():
                segments = self._apply_modifiers(content)
                return await self._adapter._send_segments(
                    ctx.get("account_id"),
                    ctx["target_type"],
                    ctx["target_id"],
                    segments,
                    reply_message_id=message_id,
                )

            return asyncio.create_task(_send())

        def Recall(self, message_id: Union[str, int]):
            ctx = self.send_context

            async def _send():
                channel_id = await self._adapter._resolve_target_channel(
                    ctx.get("account_id"), ctx["target_type"], ctx["target_id"]
                )
                return await self._adapter.call_api(
                    endpoint=f"/channels/{channel_id}/messages/{message_id}",
                    _account_id=ctx.get("account_id"),
                    method="DELETE",
                )

            return asyncio.create_task(_send())

        def Raw_ob12(self, message: Union[Dict, List[Dict]], **kwargs):
            if isinstance(message, dict):
                message = [message]

            ctx = self.send_context

            async def _send():
                segments = self._apply_modifiers(message)
                return await self._adapter._send_segments(
                    ctx.get("account_id"),
                    ctx["target_type"],
                    ctx["target_id"],
                    segments,
                )

            return asyncio.create_task(_send())

        def Raw_json(self, json_str: str):
            data = json.loads(json_str)

            ctx = self.send_context

            async def _send():
                channel_id = await self._adapter._resolve_target_channel(
                    ctx.get("account_id"), ctx["target_type"], ctx["target_id"]
                )
                endpoint = data.pop("endpoint", f"/channels/{channel_id}/messages")
                return await self._adapter.call_api(
                    endpoint=endpoint,
                    _account_id=ctx.get("account_id"),
                    method="POST",
                    _json=data,
                )

            return asyncio.create_task(_send())

    # ==================== 适配器初始化 ====================

    def __init__(self, sdk_ref=None):
        super().__init__(sdk_ref)
        self._runtime_state: Dict[str, dict] = {}
        self._converters: Dict[str, DiscordConverter] = {}
        self._connect_tasks: Dict[str, asyncio.Task] = {}
        self._dm_channels: Dict[str, str] = {}
        self._running = False
        self.default_timeout = 30
        self.default_retry_interval = 5

    def _get_config_key(self) -> str:
        return "DiscordAdapter"

    def _load_accounts(self) -> dict:
        from ErisPulse.Core.config import config as config_mgr
        from ErisPulse.runtime.config_schema import dict_to_dataclass

        key = "DiscordAdapter.accounts"
        data = config_mgr.getConfig(key)

        if not data:
            self.logger.info("未找到配置文件，创建默认账户配置")
            default_config = {
                "default": {
                    "token": "",
                    "intents": DEFAULT_INTENTS,
                    "enabled": True,
                }
            }
            try:
                config_mgr.setConfig(key, default_config)
            except Exception as e:
                self.logger.error(f"保存默认账户配置失败: {str(e)}")
            data = default_config

        accounts = {}
        for name, account_data in data.items():
            if not isinstance(account_data, dict):
                continue
            if not account_data.get("token"):
                self.logger.error(f"Bot {name} 缺少token配置，已跳过")
                continue

            instance = dict_to_dataclass(DiscordAccountConfig, account_data)
            instance.name = name
            accounts[name] = instance

        self.logger.info(f"Discord适配器初始化完成，共加载 {len(accounts)} 个机器人")
        return accounts

    # ==================== REST API ====================

    async def call_api(
        self,
        endpoint: str,
        _account_id: Optional[str] = None,
        method: str = "GET",
        _json: Optional[dict] = None,
        **params,
    ):
        account_name, account = self._resolve_account(_account_id)
        url = f"{API_BASE}{endpoint}"
        headers = {"Authorization": f"Bot {account.token}"}

        method = method.upper()

        try:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers)
            elif method == "PATCH":
                body = _json if _json is not None else params
                resp = await client.patch(url, headers=headers, json=body)
            elif method == "PUT":
                body = _json if _json is not None else params
                resp = await client.put(url, headers=headers, json=body)
            else:
                body = _json if _json is not None else params
                resp = await client.post(url, headers=headers, json=body)

            status = resp.status
            try:
                raw_response = await resp.json()
            except Exception:
                raw_response = {}

            self.logger.debug(f"账户 {account_name} API {method} {endpoint} → {status}")

            is_ok = 200 <= status < 300
            message_id = ""
            if isinstance(raw_response, dict):
                message_id = str(raw_response.get("id", ""))

            error_msg = ""
            if not is_ok and isinstance(raw_response, dict):
                error_msg = str(raw_response.get("message", ""))

            result = self.make_response(
                status="ok" if is_ok else "failed",
                retcode=0 if is_ok else 34000,
                data=raw_response if is_ok else None,
                message_id=message_id,
                message=error_msg,
                raw=raw_response,
            )
            result["discord_raw"] = raw_response
            return result

        except Exception as e:
            self.logger.error(f"账户 {account_name} 调用 Discord API 失败: {str(e)}")
            return self.make_error(
                retcode=33001,
                message=f"API调用失败: {str(e)}",
                raw=None,
            )

    async def _resolve_target_channel(
        self, account_id: str, target_type: str, target_id: str
    ) -> str:
        """将发送目标解析为 Discord channel_id（私信需先创建 DM 频道）"""
        if target_type in ("group", "channel"):
            return str(target_id)

        # 私信：创建或获取 DM 频道
        cache_key = f"{account_id}:{target_id}"
        if cache_key in self._dm_channels:
            return self._dm_channels[cache_key]

        resp = await self.call_api(
            "/users/@me/channels",
            _account_id=account_id,
            method="POST",
            recipient_id=str(target_id),
        )
        if resp.get("status") == "ok" and isinstance(resp.get("data"), dict):
            channel_id = str(resp["data"].get("id", ""))
            if channel_id:
                self._dm_channels[cache_key] = channel_id
                return channel_id

        self.logger.warning(f"创建 DM 频道失败，回退到原始 ID: {target_id}")
        return str(target_id)

    async def _send_segments(
        self,
        account_id: str,
        target_type: str,
        target_id: str,
        segments: List[Dict],
        reply_message_id: Union[str, int, None] = None,
    ):
        """将 OneBot12 消息段转换为 Discord payload 并发送"""
        content_parts = []
        embeds = []
        files = []

        for seg in segments:
            seg_type = seg.get("type", "")
            data = seg.get("data", {})

            if seg_type == "text":
                content_parts.append(data.get("text", ""))
            elif seg_type == "discord_embed":
                embed = data.get("embed")
                if embed:
                    embeds.append(embed)
            elif seg_type in ("image", "file", "video", "audio"):
                file_data = data.get("file")
                if isinstance(file_data, bytes):
                    files.append(
                        (
                            data.get("file_name", seg_type),
                            file_data,
                        )
                    )
                elif isinstance(file_data, str) and file_data:
                    content_parts.append(file_data)
            elif seg_type == "mention":
                content_parts.append(f"<@{data.get('user_id', '')}>")
            elif seg_type == "mention_all":
                content_parts.append("@everyone")
            elif seg_type == "reply":
                if reply_message_id is None:
                    reply_message_id = data.get("message_id")

        payload = {}
        if content_parts:
            payload["content"] = "".join(content_parts)
        if embeds:
            payload["embeds"] = embeds
        if reply_message_id is not None:
            payload["message_reference"] = {"message_id": str(reply_message_id)}

        # 确保 payload 非空
        if not payload and not files:
            payload["content"] = ""

        channel_id = await self._resolve_target_channel(
            account_id, target_type, target_id
        )

        if files:
            return await self._send_with_attachments(
                account_id, channel_id, payload, files
            )
        else:
            return await self.call_api(
                endpoint=f"/channels/{channel_id}/messages",
                _account_id=account_id,
                method="POST",
                _json=payload,
            )

    async def _send_with_attachments(
        self, account_id: str, channel_id: str, payload: dict, files: list
    ):
        """通过 multipart/form-data 上传附件并发送消息"""
        import aiohttp

        account_name, account = self._resolve_account(account_id)
        url = f"{API_BASE}/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {account.token}"}

        form = aiohttp.FormData()
        form.add_field(
            "payload_json",
            json.dumps(payload),
            content_type="application/json",
        )
        for i, (filename, file_bytes) in enumerate(files):
            form.add_field(
                f"files[{i}]",
                file_bytes,
                filename=filename or f"file_{i}",
                content_type="application/octet-stream",
            )

        try:
            resp = await client.post(url, headers=headers, data=form)
            status = resp.status
            try:
                raw_response = await resp.json()
            except Exception:
                raw_response = {}

            is_ok = 200 <= status < 300
            message_id = ""
            if isinstance(raw_response, dict):
                message_id = str(raw_response.get("id", ""))

            error_msg = ""
            if not is_ok and isinstance(raw_response, dict):
                error_msg = str(raw_response.get("message", ""))

            result = self.make_response(
                status="ok" if is_ok else "failed",
                retcode=0 if is_ok else 34000,
                data=raw_response if is_ok else None,
                message_id=message_id,
                message=error_msg,
                raw=raw_response,
            )
            result["discord_raw"] = raw_response
            return result
        except Exception as e:
            self.logger.error(f"账户 {account_name} 上传附件失败: {str(e)}")
            return self.make_error(
                retcode=33001,
                message=f"附件上传失败: {str(e)}",
                raw=None,
            )

    # ==================== Gateway 连接 ====================

    async def start(self):
        self._running = True

        for account_name, account in self.enabled_accounts.items():
            converter = DiscordConverter()
            self._converters[account_name] = converter

            self._runtime_state[account_name] = {
                "ws": None,
                "session_id": None,
                "seq": None,
                "heartbeat_task": None,
                "bot_id": "",
                "heartbeat_ack": True,
            }

            self._connect_tasks[account_name] = asyncio.create_task(
                self._connect_account(account_name)
            )
            self.logger.info(f"启动 Discord 账户: {account_name}")

        self.logger.info(
            f"Discord适配器启动完成，共 {len(self.enabled_accounts)} 个机器人"
        )

    async def _connect_account(self, account_name: str):
        """单个账户的 Gateway 连接主循环"""
        account = self.accounts[account_name]
        state = self._runtime_state.get(account_name, {})

        while self._running:
            try:
                # 获取 Gateway URL
                gw = await self.call_api("/gateway/bot", _account_id=account_name)
                if gw.get("status") != "ok":
                    raise ConnectionError(f"获取 Gateway URL 失败: {gw.get('message')}")
                gw_data = gw.get("data", {})
                gw_url = gw_data.get("url", "wss://gateway.discord.gg")
                gw_url = gw_url.split("?")[0]
                ws_url = f"{gw_url}?v=10&encoding=json"

                # 如果有 session，优先使用 resume_gateway_url
                if state.get("session_id") and state.get("resume_gateway_url"):
                    resume_url = state["resume_gateway_url"].split("?")[0]
                    ws_url = f"{resume_url}?v=10&encoding=json"

                # 连接 WebSocket
                ws = await client.ws_connect(ws_url)
                state["ws"] = ws
                self._runtime_state[account_name] = state
                self.logger.info(f"账户 {account_name} Gateway WebSocket 已连接")

                # 接收 HELLO
                msg = await ws.receive()
                if msg.type != WSMessage.TEXT:
                    raise ConnectionError("未收到 HELLO 消息")

                hello = json.loads(msg.data)
                if hello.get("op") != OP_HELLO:
                    raise ConnectionError(
                        f"期望 HELLO(op=10)，收到 op={hello.get('op')}"
                    )

                heartbeat_interval = (
                    hello.get("d", {}).get("heartbeat_interval", 41250) / 1000.0
                )

                # IDENTIFY 或 RESUME
                if state.get("session_id"):
                    await self._resume(account_name, account)
                else:
                    await self._identify(account_name, account)

                # 启动心跳
                state["heartbeat_ack"] = True
                state["heartbeat_task"] = asyncio.create_task(
                    self._heartbeat(account_name, heartbeat_interval)
                )

                # 监听事件
                await self._listen(account_name)

                # 连接结束，取消心跳
                ht = state.get("heartbeat_task")
                if ht and not ht.done():
                    ht.cancel()
                    try:
                        await ht
                    except asyncio.CancelledError:
                        pass

                if not self._running:
                    return

                self.logger.info(
                    f"账户 {account_name} {self.default_retry_interval}秒后重连..."
                )
                await asyncio.sleep(self.default_retry_interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(
                    f"账户 {account_name} 连接异常: {str(e)}",
                    exc_info=True,
                )
                if not self._running:
                    return
                await asyncio.sleep(self.default_retry_interval)

    async def _identify(self, account_name: str, account: DiscordAccountConfig):
        state = self._runtime_state[account_name]
        ws = state["ws"]

        identify_payload = {
            "op": OP_IDENTIFY,
            "d": {
                "token": account.token,
                "intents": account.intents,
                "properties": {
                    "os": "linux",
                    "browser": "erispulse",
                    "device": "erispulse",
                },
            },
        }
        await ws.send_text(json.dumps(identify_payload))
        self.logger.info(f"账户 {account_name} 已发送 IDENTIFY")

    async def _resume(self, account_name: str, account: DiscordAccountConfig):
        state = self._runtime_state[account_name]
        ws = state["ws"]

        resume_payload = {
            "op": OP_RESUME,
            "d": {
                "token": account.token,
                "session_id": state["session_id"],
                "seq": state["seq"],
            },
        }
        await ws.send_text(json.dumps(resume_payload))
        self.logger.info(
            f"账户 {account_name} 已发送 RESUME "
            f"(session={state['session_id']}, seq={state['seq']})"
        )

    async def _heartbeat(self, account_name: str, interval: float):
        state = self._runtime_state.get(account_name, {})

        # 首次心跳使用随机 jitter
        await asyncio.sleep(interval * random.random())

        while self._running:
            try:
                ws = state.get("ws")
                if not ws or (hasattr(ws, "closed") and ws.closed):
                    return

                state["heartbeat_ack"] = False
                seq = state.get("seq")
                await ws.send_text(json.dumps({"op": OP_HEARTBEAT, "d": seq}))
                self.logger.debug(f"账户 {account_name} 发送心跳 (seq={seq})")

                await asyncio.sleep(interval)

                if not state.get("heartbeat_ack"):
                    self.logger.warning(f"账户 {account_name} 心跳未确认，准备重连")
                    if ws and not (hasattr(ws, "closed") and ws.closed):
                        try:
                            await ws.close()
                        except Exception:
                            pass
                    return

            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"账户 {account_name} 心跳异常: {str(e)}")
                return

    async def _listen(self, account_name: str):
        state = self._runtime_state.get(account_name, {})
        ws = state.get("ws")
        if not ws:
            return

        try:
            while self._running:
                msg = await ws.receive()
                if msg.type == WSMessage.TEXT:
                    await self._handle_gateway_message(account_name, msg.data)
                elif msg.type == WSMessage.BINARY:
                    self.logger.debug(f"账户 {account_name} 收到二进制数据")
                elif msg.type == WSMessage.CLOSE:
                    self.logger.info(f"账户 {account_name} 收到 CLOSE 帧")
                    break
                elif msg.type == WSMessage.ERROR:
                    self.logger.error(f"账户 {account_name} 收到 ERROR 帧")
                    break
        except Exception as e:
            self.logger.error(
                f"账户 {account_name} 监听异常: {str(e)}",
                exc_info=True,
            )
        finally:
            try:
                bot_id = state.get("bot_id", "")
                await self.emit_meta("disconnect", bot_id)
            except Exception:
                pass

    async def _handle_gateway_message(self, account_name: str, raw_data: str):
        state = self._runtime_state.get(account_name, {})
        ws = state.get("ws")

        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            self.logger.error(f"账户 {account_name} JSON 解析失败: {raw_data[:200]}")
            return

        op = data.get("op")

        if op == OP_DISPATCH:
            event_name = data.get("t", "")
            seq = data.get("s")
            if seq is not None:
                state["seq"] = seq

            payload = data.get("d", {})

            if event_name == "READY":
                await self._handle_ready(account_name, payload)
                return

            if event_name == "RESUMED":
                self.logger.info(f"账户 {account_name} RESUME 成功")
                return

            await self._handle_dispatch(account_name, event_name, payload)

        elif op == OP_HEARTBEAT_ACK:
            state["heartbeat_ack"] = True
            self.logger.debug(f"账户 {account_name} 收到心跳确认")

        elif op == OP_HEARTBEAT:
            seq = state.get("seq")
            if ws:
                await ws.send_text(json.dumps({"op": OP_HEARTBEAT, "d": seq}))
            self.logger.debug(f"账户 {account_name} 服务器请求心跳")

        elif op == OP_RECONNECT:
            self.logger.info(f"账户 {account_name} 服务器要求重连")
            if ws and not (hasattr(ws, "closed") and ws.closed):
                try:
                    await ws.close()
                except Exception:
                    pass

        elif op == OP_INVALID_SESSION:
            resumable = data.get("d")
            self.logger.warning(f"账户 {account_name} 无效会话 (可恢复: {resumable})")
            if not resumable:
                state["session_id"] = None
                state["seq"] = None
            if ws and not (hasattr(ws, "closed") and ws.closed):
                try:
                    await asyncio.sleep(2)
                    await ws.close()
                except Exception:
                    pass

        else:
            self.logger.debug(f"账户 {account_name} 收到未知 op={op}")

    async def _handle_ready(self, account_name: str, payload: dict):
        state = self._runtime_state.get(account_name, {})
        user = payload.get("user", {})
        bot_id = str(user.get("id", ""))
        session_id = payload.get("session_id", "")
        resume_gateway_url = payload.get("resume_gateway_url", "")

        state["bot_id"] = bot_id
        state["session_id"] = session_id
        state["resume_gateway_url"] = resume_gateway_url

        # 更新转换器
        converter = self._converters.get(account_name)
        if converter:
            converter.bot_id = bot_id

        await self.emit_meta("connect", bot_id)
        self.logger.info(
            f"账户 {account_name} 已就绪 (bot_id: {bot_id}, session: {session_id})"
        )

    async def _handle_dispatch(self, account_name: str, event_name: str, data: dict):
        converter = self._converters.get(account_name)
        if not converter:
            return

        onebot_event = converter.convert(data, event_name)
        if onebot_event:
            from ErisPulse.Core import adapter as adapter_mgr

            await adapter_mgr.emit(onebot_event)

    # ==================== 关闭 ====================

    async def shutdown(self):
        self._running = False

        # 取消连接任务
        for task in self._connect_tasks.values():
            if not task.done():
                task.cancel()
        if self._connect_tasks:
            await asyncio.gather(*self._connect_tasks.values(), return_exceptions=True)
        self._connect_tasks.clear()

        # 关闭 WebSocket 连接和心跳任务
        for account_name, state in self._runtime_state.items():
            ht = state.get("heartbeat_task")
            if ht and not ht.done():
                ht.cancel()

            ws = state.get("ws")
            bot_id = state.get("bot_id", "")
            if ws and hasattr(ws, "closed") and not ws.closed:
                try:
                    await ws.close()
                except Exception as e:
                    self.logger.error(
                        f"关闭账户 {account_name} WebSocket 失败: {str(e)}"
                    )

            try:
                await self.emit_meta("disconnect", bot_id)
            except Exception:
                pass

        self._runtime_state.clear()
        self._converters.clear()
        self._dm_channels.clear()

        try:
            unregister_platform_event_methods("discord")
        except Exception:
            pass

        self.logger.info("Discord适配器已关闭")
