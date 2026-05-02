# Channel 配置参考

## 钉钉 (DingTalk)

| 参数 | 必填 | 说明 |
|------|------|------|
| `client_id` | ✅ | 钉钉应用 AppKey (Client ID) |
| `client_secret` | ✅ | 钉钉应用 AppSecret (Client Secret) |
| `robot_code` | ❌ | 机器人编码，群聊时建议配置，默认等于 client_id |
| `message_type` | ❌ | 回复格式: `markdown`(默认) 或 `text` |

获取方式：钉钉开发者后台 → 应用开发 → 创建应用 → 凭证与基础信息

## 飞书 (Feishu)

| 参数 | 必填 | 说明 |
|------|------|------|
| `app_id` | ✅ | 飞书应用 App ID |
| `app_secret` | ✅ | 飞书应用 App Secret |
| `encrypt_key` | ❌ | 事件订阅加密 Key |
| `verification_token` | ❌ | 事件订阅验证 Token |
| `domain` | ❌ | `feishu`(国内,默认) 或 `lark`(国际版) |

获取方式：飞书开发者后台 → 创建应用 → 凭证与基础信息 → 开启机器人能力

## 企业微信 (WeCom) — 待实现

| 参数 | 必填 | 说明 |
|------|------|------|
| `bot_id` | ✅ | 企微机器人 Bot ID |
| `secret` | ✅ | 企微机器人 Secret |
