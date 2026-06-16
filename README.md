# ErisPulse Discord Adapter

[English](#english) | [中文](#中文)

---

<a id="english"></a>

## English

A Discord Bot adapter for the [ErisPulse](https://github.com/ErisPulse/ErisPulse/) framework, implementing multi-account support, diverse message types, and platform-specific event handling via Discord Gateway (WebSocket) and REST API v10.

### Features

- **Multi-Account**: Run multiple Discord Bots simultaneously
- **Gateway WebSocket**: Full HELLO / IDENTIFY / Heartbeat / RESUME flow
- **Auto-Reconnect**: RESUME session recovery, no message loss
- **REST API v10**: Complete Discord HTTP API access
- **Embed Support**: Send and receive rich embed messages
- **File Upload**: multipart/form-data attachment uploads
- **DM**: Auto-create DM channels for private messaging
- **Thread Support**: Track and interact with Discord threads

### Installation

```bash
epsdk install Discord
```

### Configuration

Add to `config/config.toml`:

```toml
[DiscordAdapter.accounts.default]
token = "YOUR_BOT_TOKEN"
intents = 33281
enabled = true

# Multi-account example
[DiscordAdapter.accounts.bot2]
token = "ANOTHER_BOT_TOKEN"
intents = 33281
enabled = true
```

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | string | Yes | Discord Bot Token |
| `intents` | int | No | Gateway Intents bitmask (default 33281) |
| `enabled` | bool | No | Enable this account (default true) |

> `bot_id` is discovered automatically at runtime from the Gateway READY event — no need to configure it.

#### Intents

Intents is a bitmask, default `33281` = `GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT`:

| Intent | Value | Description |
|--------|-------|-------------|
| GUILDS | `1 << 0` (1) | Guild-related events |
| GUILD_MEMBERS | `1 << 1` (2) | Member events (requires Privileged) |
| GUILD_MESSAGES | `1 << 9` (512) | Guild message events |
| MESSAGE_CONTENT | `1 << 15` (32768) | Message content (requires Privileged) |

> **Note**: `MESSAGE_CONTENT` and `GUILD_MEMBERS` are Privileged Intents. Enable them in the [Discord Developer Portal](https://discord.com/developers/applications) → Bot → Privileged Gateway Intents.

#### Inviting the Bot

The bot must be invited to a server before it can send/receive messages. Construct an OAuth2 URL:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_ID&permissions=8&scope=bot
```

- `client_id` = your Bot's Application ID (the `bot_id` shown in logs after READY)
- `permissions=8` = Administrator (adjust as needed via [Discord Permission Calculator](https://discordapi.com/permissions.html))
- Add `applications.commands` to `scope` if using slash commands

### Quick Start

```python
from ErisPulse import sdk
from ErisPulse.Core.Event import message

discord = sdk.adapter.get("discord")

@message.on_message()
async def handle_message(event):
    if event.get_platform() != "discord":
        return

    text = event.get_text()
    channel_id = event.get_channel_id()  # Discord channel ID

    if text == "hello":
        # Reply to the channel where the message was received
        await event.reply("Hello from Discord!")

async def main():
    await sdk.run(keep_running=True)
```

### Sending Messages

#### Text

```python
# Guild channel message
await discord.Send.To("channel", channel_id).Text("Hello World!")

# Private message (auto-creates DM channel)
await discord.Send.To("user", user_id).Text("DM content")
```

#### Embed

```python
embed = {
    "title": "Title",
    "description": "Description",
    "color": 5814783,
    "fields": [
        {"name": "Field", "value": "Value", "inline": False}
    ],
    "footer": {"text": "Footer text"},
}
await discord.Send.To("channel", channel_id).Embed(embed)
```

#### Media

```python
# Image (URL)
await discord.Send.To("channel", channel_id).Image("https://example.com/image.png")

# Image (binary)
with open("image.png", "rb") as f:
    image_data = f.read()
await discord.Send.To("channel", channel_id).Image(image_data, filename="photo.png")

# File
await discord.Send.To("channel", channel_id).File("https://example.com/doc.pdf")
await discord.Send.To("channel", channel_id).File(file_bytes, filename="report.pdf")
```

#### Reply

```python
# Chain modifier
await discord.Send.To("channel", channel_id).Reply(msg_id).Text("Reply content")

# One-shot
await discord.Send.To("channel", channel_id).Reply("Reply content", msg_id)
```

#### Mentions

```python
# @single user
await discord.Send.To("channel", channel_id).At("user_id").Text("Hello")

# @multiple users
await discord.Send.To("channel", channel_id).At("user1").At("user2").Text("Hi everyone")

# @everyone
await discord.Send.To("channel", channel_id).AtAll().Text("Announcement")
```

#### Message Operations

```python
# Delete (recall) a message
await discord.Send.To("channel", channel_id).Recall(msg_id)
```

#### OneBot12 Format

```python
ob12_msg = [{"type": "text", "data": {"text": "Hello"}}]
await discord.Send.To("channel", channel_id).Raw_ob12(ob12_msg)
```

#### Multi-Account

```python
# By bot_id (recommended)
await discord.Send.Using(event.get("self", {}).get("user_id")).To("channel", channel_id).Text("Hello")

# By account name
await discord.Send.Using("bot2").To("channel", channel_id).Text("Hello")
```

### Discord-Specific Event Methods

The event object provides Discord-specific methods (requires `platform == "discord"`):

```python
@message.on_message()
async def handle(event):
    if event.get_platform() != "discord":
        return

    channel_id = event.get_channel_id()    # Discord channel ID
    guild_id = event.get_guild_id()        # Guild ID (empty for DMs)
    username = event.get_username()         # Sender username
    global_name = event.get_global_name()   # Display name
    is_dm = event.is_dm()                   # Is a DM?
    embeds = event.get_embeds()             # Embed list
    attachments = event.get_attachments()   # Attachment list
```

### Event Types

#### Message Events

| Discord Event | OB12 detail_type | Description |
|---------------|-------------------|-------------|
| MESSAGE_CREATE | `channel` / `private` | Guild channel / DM message |
| MESSAGE_UPDATE | `channel` / `private` | Message edited |
| MESSAGE_DELETE | `group_message_delete` | Message deleted |

#### Notice Events

| detail_type | Description |
|-------------|-------------|
| `group_member_increase` | Member joined guild |
| `group_member_decrease` | Member left guild |
| `group_member_update` | Member info updated |
| `group_role_create` / `group_role_delete` / `group_role_update` | Role changes |
| `channel_create` / `channel_delete` / `channel_update` | Channel changes |
| `group_message_reaction_add` / `group_message_reaction_remove` | Reaction changes |
| `typing` | User typing |

#### Request Events

| detail_type | Description |
|-------------|-------------|
| `interaction` | Slash command / button interaction |

#### Message Segment Types

| Type | Description |
|------|-------------|
| `text` | Plain text |
| `mention` / `mention_all` | @user / @everyone |
| `reply` | Reply reference |
| `image` / `file` / `video` / `audio` | Media (URL or bytes) |
| `discord_embed` | Discord Embed (extension) |

### Session Types

| Scenario | Receive detail_type | Send type | Target ID |
|----------|---------------------|-----------|-----------|
| Guild channel | `channel` | `channel` | channel_id |
| DM | `private` | `user` | user_id |

### Contributing

Issues and Pull Requests are welcome.

### License

MIT

---

<a id="中文"></a>

## 中文

基于 [ErisPulse](https://github.com/ErisPulse/ErisPulse/) 框架的 Discord Bot 适配器，通过 Discord Gateway (WebSocket) 和 REST API v10 实现多账户支持、多种消息类型收发和平台特有事件处理。

### 特性

- **多账户支持**：同时运行多个 Discord Bot
- **Gateway WebSocket**：完整实现 HELLO / IDENTIFY / 心跳 / RESUME 流程
- **自动断线重连**：支持 RESUME 恢复会话，消息不丢失
- **REST API v10**：完整的 Discord HTTP API 调用
- **Embed 支持**：发送和接收富文本嵌入消息
- **文件上传**：支持 multipart/form-data 上传附件
- **DM 私信**：自动创建 DM 频道，支持私信收发
- **Thread 支持**：跟踪和交互 Discord 话题

### 安装

```bash
epsdk install Discord
```

### 配置

在 `config/config.toml` 中添加：

```toml
[DiscordAdapter.accounts.default]
token = "YOUR_BOT_TOKEN"
intents = 33281
enabled = true

# 多账户示例
[DiscordAdapter.accounts.bot2]
token = "ANOTHER_BOT_TOKEN"
intents = 33281
enabled = true
```

#### 配置字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `token` | string | 是 | Discord Bot Token |
| `intents` | int | 否 | Gateway Intents 位掩码（默认 33281） |
| `enabled` | bool | 否 | 是否启用（默认 true） |

> `bot_id` 运行时从 Gateway READY 事件自动发现，无需配置。

#### Intents 说明

Intents 是位掩码，默认 `33281` = `GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT`：

| Intent | 值 | 说明 |
|-------|------|------|
| GUILDS | `1 << 0` (1) | 服务器相关事件 |
| GUILD_MEMBERS | `1 << 1` (2) | 成员相关事件（需 Privileged） |
| GUILD_MESSAGES | `1 << 9` (512) | 服务器消息事件 |
| MESSAGE_CONTENT | `1 << 15` (32768) | 消息内容（需 Privileged） |

> **注意**：`MESSAGE_CONTENT` 和 `GUILD_MEMBERS` 是 Privileged Intents，需在 [Discord Developer Portal](https://discord.com/developers/applications) 的 Bot 设置页开启。

#### 邀请机器人

机器人必须先被邀请加入服务器才能收发消息。构造 OAuth2 邀请链接：

```
https://discord.com/api/oauth2/authorize?client_id=你的BOT_ID&permissions=8&scope=bot
```

- `client_id` = 你的 Bot Application ID（READY 后日志中显示的 `bot_id`）
- `permissions=8` = 管理员权限（可通过 [Discord Permission Calculator](https://discordapi.com/permissions.html) 自行计算）
- 如需使用斜杠命令，在 `scope` 中添加 `applications.commands`

### 快速开始

```python
from ErisPulse import sdk
from ErisPulse.Core.Event import message

discord = sdk.adapter.get("discord")

@message.on_message()
async def handle_message(event):
    if event.get_platform() != "discord":
        return

    text = event.get_text()
    channel_id = event.get_channel_id()  # Discord 频道 ID

    if text == "hello":
        # 回复到收到消息的频道
        await event.reply("Hello from Discord!")

async def main():
    await sdk.run(keep_running=True)
```

### 发送消息

#### 文本消息

```python
# 服务器频道消息
await discord.Send.To("channel", channel_id).Text("Hello World!")

# 私信（自动创建 DM 频道）
await discord.Send.To("user", user_id).Text("私信内容")
```

#### Embed 嵌入消息

```python
embed = {
    "title": "标题",
    "description": "描述内容",
    "color": 5814783,
    "fields": [
        {"name": "字段名", "value": "字段值", "inline": False}
    ],
    "footer": {"text": "页脚文字"},
}
await discord.Send.To("channel", channel_id).Embed(embed)
```

#### 媒体消息

```python
# 发送图片（URL）
await discord.Send.To("channel", channel_id).Image("https://example.com/image.png")

# 发送图片（二进制数据）
with open("image.png", "rb") as f:
    image_data = f.read()
await discord.Send.To("channel", channel_id).Image(image_data, filename="photo.png")

# 发送文件
await discord.Send.To("channel", channel_id).File("https://example.com/doc.pdf")
await discord.Send.To("channel", channel_id).File(file_bytes, filename="report.pdf")
```

#### 回复消息

```python
# 链式修饰回复
await discord.Send.To("channel", channel_id).Reply(msg_id).Text("回复内容")

# 便捷方法（一步发送）
await discord.Send.To("channel", channel_id).Reply("回复内容", msg_id)
```

#### 链式 @提及

```python
# @单个用户
await discord.Send.To("channel", channel_id).At("user_id").Text("你好")

# @多个用户
await discord.Send.To("channel", channel_id).At("user1").At("user2").Text("大家好")

# @全体
await discord.Send.To("channel", channel_id).AtAll().Text("公告")
```

#### 消息操作

```python
# 撤回消息
await discord.Send.To("channel", channel_id).Recall(msg_id)
```

#### OneBot12 格式消息

```python
ob12_msg = [{"type": "text", "data": {"text": "Hello"}}]
await discord.Send.To("channel", channel_id).Raw_ob12(ob12_msg)
```

#### 多账户发送

```python
# 通过 bot_id（推荐）
await discord.Send.Using(event.get("self", {}).get("user_id")).To("channel", channel_id).Text("Hello")

# 通过账户名
await discord.Send.Using("bot2").To("channel", channel_id).Text("Hello")
```

### Discord 特有方法

事件对象提供以下 Discord 专属方法（需 `platform == "discord"`）：

```python
@message.on_message()
async def handle(event):
    if event.get_platform() != "discord":
        return

    channel_id = event.get_channel_id()    # Discord 频道 ID
    guild_id = event.get_guild_id()        # 服务器 ID（私信为空）
    username = event.get_username()         # 发送者用户名
    global_name = event.get_global_name()   # 显示名
    is_dm = event.is_dm()                   # 是否私信
    embeds = event.get_embeds()             # Embed 列表
    attachments = event.get_attachments()   # 附件列表
```

### 事件类型

#### 消息事件

| Discord 事件 | OB12 detail_type | 说明 |
|---------------|-------------------|------|
| MESSAGE_CREATE | `channel` / `private` | 服务器频道 / 私信消息 |
| MESSAGE_UPDATE | `channel` / `private` | 消息编辑 |
| MESSAGE_DELETE | `group_message_delete` | 消息删除 |

#### 通知事件

| detail_type | 说明 |
|-------------|------|
| `group_member_increase` | 成员加入服务器 |
| `group_member_decrease` | 成员离开服务器 |
| `group_member_update` | 成员信息更新 |
| `group_role_create` / `group_role_delete` / `group_role_update` | 身份组变更 |
| `channel_create` / `channel_delete` / `channel_update` | 频道变更 |
| `group_message_reaction_add` / `group_message_reaction_remove` | 表情回应变更 |
| `typing` | 用户正在输入 |

#### 请求事件

| detail_type | 说明 |
|-------------|------|
| `interaction` | 斜杠命令 / 按钮交互 |

#### 消息段类型

| 类型 | 说明 |
|------|------|
| `text` | 纯文本 |
| `mention` / `mention_all` | @用户 / @全体 |
| `reply` | 回复引用 |
| `image` / `file` / `video` / `audio` | 媒体（URL 或二进制） |
| `discord_embed` | Discord Embed（扩展） |

### 会话类型

| 场景 | 接收 detail_type | 发送类型 | 目标 ID |
|------|------------------|----------|---------|
| 服务器频道 | `channel` | `channel` | channel_id |
| 私信 | `private` | `user` | user_id |

### 贡献

欢迎提交 Issue 和 Pull Request。

### License

MIT
