# NoWork 使用手册

## 快速开始

欢迎使用 NoWork！按照以下三步即可开始使用：

### 第一步：配置模型提供商

> ⚠️ **这是必须的第一步。** 没有配置模型，所有 Worker 都无法运行。

1. 点击左侧导航栏的 **Models**（模型管理）
2. 点击左侧列表中的 **+ Add Provider**（添加提供商）
3. 填写以下信息：

| 字段 | 说明 | 示例 |
|------|------|------|
| **Provider ID** | 提供商的唯一标识，英文小写，用 `-` 连接 | `qwen-coding` |
| **Name** | 显示名称 | `通义千问 Coding` |
| **Type** | 协议类型，目前支持 OpenAI Compatible | 保持默认即可 |
| **Base URL** | API 的基础地址 | `https://coding.dashscope.aliyuncs.com/v1` |
| **API Key** | 你的 API 密钥 | `sk-xxxxx` |

4. 点击 **Fetch from API**（从 API 获取模型列表）自动拉取可用模型，或点击 **+ Add Model** 手动添加
5. 对于每个模型，设置：
   - **Model ID**：模型的本地 ID（如 `qwen3.6-plus`）
   - **Name**：显示名称
   - **Image**：是否支持图片输入
   - **Video**：是否支持视频输入
6. 点击 **Save** 保存

**常见 API 地址：**

| 服务商 | Base URL |
|--------|----------|
| 阿里云百炼（通义千问） | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| 智谱（GLM） | `https://open.bigmodel.cn/api/paas/v4` |
| 月之暗面（Moonshot） | `https://api.moonshot.cn/v1` |

> 💡 **提示：** 也可以直接编辑配置文件。模型配置文件位于 `server/config/models/` 目录下，参考 `*.example.yaml` 模板。

### 第二步：配置默认模型

编辑 `server/config/config.yaml`，确保 `default_model` 指向你刚配置的模型：

```yaml
default_model: qwen-coding/qwen3.6-plus
```

格式为 `{Provider ID}/{Model ID}`。保存后重启服务生效。

> 💡 **提示：** 所有未单独指定模型的 Worker 会自动使用此默认模型。

### 第三步：开始对话

1. 点击左侧导航栏的 **Chat**（聊天）
2. 左侧的 Worker 列表中选择一个 Worker（如 Code Agent）
3. 在底部输入框输入消息，按 Enter 发送
4. Worker 会流式返回响应

---

## 核心功能

### 💬 聊天（Chat）

**会话管理：**
- 点击 **+** 按钮创建新会话
- 会话标签显示创建时间，点击切换
- 每个会话独立维护上下文

**工作区选择：**
- 输入框左侧的目录按钮可以选择当前会话绑定的目录
- `All` 表示使用 Worker 配置的所有目录
- 选择特定目录后，Worker 只能访问这些目录中的文件

**附件：**
- 📎 **文件**：附加代码/文本文件
- 🖼️ **图片**：附加截图（需要模型支持 Image）
- 🎬 **视频**：附加视频（需要模型支持 Video）
- 🎤 **语音**：点击麦克风按钮，语音转文字输入（需要浏览器支持）

**Worker 设置：**
- 点击聊天头部的 ⚙ 齿轮按钮，打开当前 Worker 的设置侧边栏
- 可以在此修改 Worker 的系统提示、模型、工具等配置

### 👷 Worker 管理（Workers）

Worker 是 NoWork 的核心执行单元，可以是：
- **Agent**：单智能体，执行独立任务
- **Team**：多智能体协作
- **Workflow**：流程编排

**创建/编辑 Worker：**
1. 进入 Workers 页面
2. 选择 Agent / Team / Workflow 标签
3. 点击列表中的 Worker 进入编辑

**Worker 配置项：**

| 区域 | 说明 |
|------|------|
| **基本信息** | 名称、描述、系统提示（Instructions） |
| **模型** | 选择该 Worker 使用的模型提供商和具体模型 |
| **工具** | 启用/禁用可用工具（如 CodingTools） |
| **工作区** | 配置 Worker 可访问的目录和权限（读写/只读） |
| **MCP 服务器** | 绑定 Model Context Protocol 服务器 |
| **知识库** | 绑定向量知识库 |
| **技能** | 启用/禁用可用技能 |
| **学习** | 查看和管理用户画像、记忆数据 |
| **成员** | 管理多智能体成员（Team 类型） |

### ⏰ 定时任务（Schedules）

定时任务可以自动在指定时间触发 Worker 执行。

**创建定时任务：**
1. 进入 Schedules 页面
2. 点击 **New Schedule**
3. 配置：
   - **Name**：任务名称（如"每日晨报"）
   - **Worker**：绑定的 Worker
   - **Trigger**：触发方式
     - `Daily`：每天固定时间
     - `Weekly`：每周指定星期几的固定时间
   - **Time**：触发时间（HH:mm）
   - **Prompt**：触发时发送给 Worker 的提示词
   - **Misfire Policy**：错过执行的策略
     - `Run once when app returns`：应用恢复后执行一次
     - `Skip missed run`：跳过错过的执行

**执行记录：**
- 下方显示历史运行记录
- 包含状态（Success/Failed）、计划时间、关联会话
- 点击 **Open Worker Chat** 可跳转到对应会话

> ⚠️ **注意：** 定时任务需要应用处于运行状态才能触发。

### 📚 技能（Skills）

技能是可复用的提示词包，增强 Worker 的能力。

- 浏览已安装的技能
- 点击技能查看详情（SKILL.md 内容）
- 通过 **Install Skill** 安装新技能（本地目录或 URL）

### 🧩 扩展（Extensions）

管理可选的功能扩展包：
- **Embedding Models**：文本嵌入模型（用于知识库）
- **Vector Databases**：向量数据库驱动

### 🔌 MCP 服务器（MCP）

配置 Model Context Protocol 服务器连接，为 Worker 提供外部工具和数据源。

### ⚙️ 设置（Settings）

- **语言切换**：在中文和英文之间切换界面语言
- **版本信息**：查看当前版本，检查更新
- **开源许可**：查看 MIT License

---

## 配置文件参考

### 目录结构

```
server/config/
├── config.yaml              # 主配置（API Key、默认模型等）
├── models/                  # 模型提供商配置
│   ├── *.example.yaml       # 示例模板（已提交到 Git）
│   └── *.yaml               # 实际配置（已加入 .gitignore）
└── workers/                 # Worker 配置
    └── *.yaml               # 各 Worker 的配置文件
```

### config.yaml 关键字段

```yaml
server:
  host: 127.0.0.1
  port: 18080
default_model: provider-id/model-id   # 默认模型
models:
  - provider-id                        # 启用的提供商列表
workers:
  - worker-name                        # 启用的 Worker 列表
```

### 模型提供商配置（models/*.yaml）

```yaml
provider: openai
name: 显示名称
type: openai_compatible
base_url: https://api.example.com/v1
api_key: YOUR_API_KEY
models:
  model-id:
    name: 显示名称
    image: true    # 是否支持图片
    video: false   # 是否支持视频
```

---

## 常见问题

### Q: Worker 回复报错"未配置 default_model"
**A:** 编辑 `server/config/config.yaml`，添加或修改 `default_model: provider-id/model-id`，然后重启服务。

### Q: Worker 无法访问文件
**A:** 检查 Worker 配置中的 `workspaces` 部分，确保目标目录在列表中且权限正确（read-write）。

### Q: 定时任务没有执行
**A:** 定时任务需要应用在运行中。检查任务是否为 Enabled 状态，确认时间设置正确。

### Q: 语音输入不可用
**A:** 语音输入使用浏览器内置的 Web Speech API，需要 Chromium 内核浏览器或 WebView2。确保麦克风权限已授予。

### Q: 如何添加新的模型提供商？
**A:** 进入 Models 页面 → 点击 + Add Provider → 填写 Provider ID、Base URL、API Key → Fetch from API 或手动添加模型 → Save。

---

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 发送消息 |
| `Shift + Enter` | 换行 |
