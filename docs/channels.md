# Channel 配置指南

频道（Channel）将即时通讯平台连接到 Worker，让你直接在钉钉、飞书等聊天工具中与 AI 对话。

## 配置方式

有两种配置方式：

- **Web UI**（推荐）— 在 NoWork 界面的「Channels」页面，点击 Add Channel，填写凭据即可
- **配置文件** — 编辑 `server/config/channels.yaml`（参考 `channels.yaml.example` 模板）

---

## 钉钉 (DingTalk)

### 创建钉钉应用

1. 打开 [钉钉开发者后台](https://open-dev.dingtalk.com/)
2. 进入「应用开发 → 企业内部应用 → 钉钉应用 → 创建应用」
3. 在「应用能力 → 添加应用能力」中添加 **「机器人」**
4. 配置机器人基础信息，将消息接收模式设为 **Stream 模式**（流式接收），点击发布
5. 在「应用发布 → 版本管理与发布」中创建新版本，填写信息后保存
6. 在「基础信息 → 凭证与基础信息」中获取 **Client ID** 和 **Client Secret**
7. （可选）在「安全设置 → 服务器出口 IP」中添加公网 IP（下载图片/文件时需要）

### 配置参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `client_id` | ✅ | 钉钉应用 AppKey (Client ID) |
| `client_secret` | ✅ | 钉钉应用 AppSecret (Client Secret) |
| `robot_code` | ❌ | 机器人编码，群聊时建议配置，默认等于 client_id |
| `message_type` | ❌ | 回复格式: `markdown`(默认) 或 `text` |

### 配置文件示例

```yaml
channels:
  my-dingtalk:
    platform: dingtalk
    name: "钉钉助手"
    worker_id: code-agent
    enabled: true
    config:
      client_id: "your-client-id"
      client_secret: "your-client-secret"
      message_type: markdown
```

> 💡 在钉钉「消息」栏搜索机器人名称即可开始对话。也可通过「群设置 → 机器人 → 添加机器人」将机器人添加到群聊。

---

## 飞书 (Feishu)

### 创建飞书应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，创建企业自建应用
2. 在「凭证与基础信息」中获取 **App ID** 和 **App Secret**
3. ⚠️ **重要：先在 NoWork 填写 App ID/Secret 并启动服务**，再回到飞书开放平台继续配置
4. 在「能力」中启用 **「机器人」**
5. 在「权限管理」中点击「批量导入」，粘贴以下 JSON：

```json
{
  "scopes": {
    "tenant": [
      "im:chat",
      "im:message",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:resource",
      "contact:user.base:readonly"
    ],
    "user": []
  }
}
```

6. 在「事件与回调」中，选择订阅方式为 **长连接（WebSocket）** 模式（无需公网 IP）
7. 点击「添加事件」，搜索 **「接收消息」**，订阅 **「接收消息 v2.0」**
8. 在「应用发布 → 版本管理与发布」中创建版本，填写信息，**保存并发布**

> ⚠️ 飞书的操作顺序很关键：必须先在 NoWork 填写 App ID/Secret 并启动服务，再在开放平台配置长连接，否则验证会失败。如果仍显示错误，尝试重启 NoWork 服务。

### 配置参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `app_id` | ✅ | 飞书应用 App ID |
| `app_secret` | ✅ | 飞书应用 App Secret |
| `encrypt_key` | ❌ | 事件订阅加密 Key |
| `verification_token` | ❌ | 事件订阅验证 Token |
| `domain` | ❌ | `feishu`(国内,默认) 或 `lark`(国际版) |

### 配置文件示例

```yaml
channels:
  my-feishu:
    platform: feishu
    name: "飞书助手"
    worker_id: code-agent
    enabled: true
    config:
      app_id: "cli_xxxxxxxxxxxxxxxx"
      app_secret: "your-app-secret"
      domain: feishu
```

> 💡 飞书使用 WebSocket 长连接接收消息，无需公网 IP 或 Webhook。发送消息走飞书 Open API，支持文本和富文本格式。支持单聊和群聊。

---

## 企业微信 (WeCom) — 待实现

| 参数 | 必填 | 说明 |
|------|------|------|
| `bot_id` | ✅ | 企微机器人 Bot ID |
| `secret` | ✅ | 企微机器人 Secret |

企业微信频道正在开发中，敬请期待。

---

## 常见问题

### Q: 钉钉下载图片报 `IpNotInWhiteList` 错误
**A:** 在钉钉开发者后台的「安全设置 → 服务器出口 IP」中添加运行 NoWork 的机器的公网 IP。可在终端执行 `curl ifconfig.me` 查看公网 IP。

### Q: 飞书长连接验证失败
**A:** 确认操作顺序：先在 NoWork 填写 App ID/Secret 并启动服务 → 再回飞书开放平台配置长连接。如果仍失败，尝试重启 NoWork 服务后再配置。

### Q: 同一个 Worker 能绑定多个频道吗？
**A:** 可以。同一个 Worker 可以绑定不同平台的频道（如同时绑定钉钉和飞书），但同一个 Worker 不能绑定两个相同平台的相同应用（同一 Worker + 同一 Client ID = 冲突）。

### Q: 频道消息如何路由到 Worker？
**A:** 每个频道绑定一个 Worker。频道收到消息后，会自动创建或恢复与该 Worker 的会话（Session），消息通过会话发送给 Worker 处理。同一用户/群的后续消息会路由到同一会话。
