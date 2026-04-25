<div align="center">

# NoWork

**Agents do the work. You don't have to.**

一个桌面端 AI Agent 工作空间。每个 Agent 或 Team 都像一个聊天联系人。
选择一个 Worker，发起对话，然后把规划、编码、审查、调研、文档处理等工作交给它们。

组建你的 AI 工作团队 —— 全部放进一个聊天窗口里。

[English](./README.md)

</div>

---

## 📸 截图

#### 🖥️ 主界面
*一个干净的、联系人式的多 Worker 对话工作区。*
![Main Interface](asserts/main.png)

#### 🚀 示例：构建一个番茄钟应用
*规划、编码、审查三个 Agent 在同一个桌面应用里协作完成任务。*
![Demo Task](asserts/demo.png)

---

## NoWork 是什么？

NoWork 是一个**桌面优先的多 Agent 应用**，专注于实际工作场景：

- **编码开发** —— 规划、实现、审查、调试
- **文档处理** —— Word、Excel、PowerPoint、PDF
- **信息调研** —— 网页浏览、总结提炼、技术研究
- **持续工作流** —— 长对话、定时任务、可复用 Worker

你不需要在 Prompt、终端、脚本之间来回切换，只需要像和联系人聊天一样，把任务交给不同的 Worker。

---

## 🤔 为什么做 NoWork？

命令行 AI 工具很强，但对很多人来说，使用门槛依然偏高。现有的一些桌面封装要么不够稳定，要么太薄，要么仍然依赖手动配置环境。

NoWork 选择了另一条路：

- **桌面优先，而不是终端优先** —— 安装后即可使用，不依赖 CLI 工作流
- **聊天原生交互** —— 每个 Agent / Team 就是一个联系人，任务委派更自然
- **内置运行时** —— 应用自带后端和嵌入式 Python 运行时
- **本地工作区访问** —— Agent 可以在受控目录内直接处理真实文件
- **适合个人与小团队** —— 提供实用的多 Agent 自动化，而不是复杂的平台系统

目标很简单：让 AI 去处理重复劳动，把你的注意力留给判断和结果。

---

## ✨ 核心能力

| 能力 | 说明 |
|---|---|
| **联系人式 Worker** | 每个 Agent / Team 都像一个聊天联系人，点击即可开始工作。 |
| **多 Agent 协作** | 内置规划、编码、审查、架构、调研、文档处理等 Worker。 |
| **50+ 模型供应商** | 基于 [Agno](https://github.com/agno-agi/agno)。支持 OpenAI、Anthropic、Google、DeepSeek、Qwen、Ollama、vLLM 等众多模型。 |
| **长对话连续性** | 自动上下文压缩（Compaction），帮助长会话持续保留有效状态。 |
| **安全工作区访问** | 文件与 Shell 操作仅限于配置好的目录和权限范围内。 |
| **文档处理技能** | 内置 Word、Excel、PowerPoint、PDF 等技能。 |
| **定时执行** | 支持按计划定时运行 Worker。 |
| **MCP 集成** | 通过 Model Context Protocol 接入外部工具。 |
| **桌面原生打包** | 基于 Tauri，内置后端与嵌入式 Python 运行时。 |
| **双语界面** | 支持 English / 简体中文，即时切换。 |

---

## 🚀 快速开始

### 面向终端用户

1. **下载** 最新版本：[Releases 页面](https://github.com/yeyan00/nowork/releases)
2. **安装** 桌面应用
3. **配置模型供应商**
4. **选择一个 Worker**
5. **开始聊天并委派任务**

### 最小模型配置

先创建一个模型供应商配置文件，例如：

```yaml
# server/config/models/my-provider.yaml
provider_id: my-provider
name: 我的供应商
base_url: https://api.openai.com/v1
api_key: sk-xxx
models:
  - id: gpt-4o
    name: GPT-4o
    image: true
    video: false
```

然后设置默认模型：

```yaml
# server/config/config.yaml
default_model: my-provider/gpt-4o
```

完成后，打开应用，选择一个 Worker，直接开始聊天即可。

---

## 🧠 内置 Worker

NoWork 默认内置了一组面向工程与文档工作的实用 Worker。

| Worker | 职责 | 类型 |
|---|---|---|
| Code Agent | 编写、编辑、调试代码 | Agent |
| Planning Engineer | 需求分析与实施方案规划 | Agent |
| Implementation Engineer | 按计划逐步执行实现 | Agent |
| Architecture Reviewer | 只读代码审查与风险分析 | Agent |
| Code Explorer | 搜索、浏览、理解代码库 | Agent |
| Documentation Researcher | 编写文档与技术调研 | Agent |
| Doc Agent | Office / PDF 文档处理与网页调研 | Agent |
| Product R&D Team | 规划 → 编码 → 审查 的团队流水线 | Team |

> Worker 采用 YAML 配置驱动 —— 你可以在不修改应用代码的情况下新增、删除或定制它们。

---

## ⚙️ 配置

| 文件 | 用途 |
|---|---|
| `server/config/config.yaml` | 全局配置：默认模型、工具、服务设置 |
| `server/config/models/*.yaml` | 模型供应商定义、API Key、接口地址、能力 |
| `server/config/workers/*.yaml` | Worker 定义：指令、工具、工作区、历史、学习配置 |
| `server/config/mcp.yaml` | MCP 服务连接配置 |

### Worker 配置示例

```yaml
# server/config/workers/my-worker.yaml
agent:
  id: my-worker
  name: My Worker
  instructions: 你是一个有帮助的编程助手。
tools:
  - module: app.tools.codingTools
    class: CodingTools
    config:
      base_dirs:
        - C:/Users/me/projects
workspaces:
  - path: C:/Users/me/projects
    permission: read-write
history:
  enable_compaction: true
```

---

## 🏗️ 架构

NoWork 由 Tauri 桌面外壳、React 前端，以及本地运行的 FastAPI + Agno 后端组成，并内置嵌入式 Python 运行时。

```text
┌─ Tauri 桌面端 (Rust) ─────────────────────────────┐
│                                                   │
│  ┌─ React 前端 (Vite + TypeScript) ─────────────┐ │
│  │  导航栏 │ Worker 列表 │ 聊天工作区            │ │
│  │  语音   │ 定时任务   │ 设置 │ 帮助            │ │
│  └──────────────────────────────────────────────┘ │
│                     HTTP / SSE                    │
│  ┌─ Python 后端 (FastAPI) ─────────────────────┐ │
│  │  Agno AgentOS ─ Agent / Team / Workflow     │ │
│  │  CodingTools（沙箱 Shell + 文件操作）       │ │
│  │  CompactionManager（上下文管理）            │ │
│  │  MCP Client │ Knowledge Base │ Skills       │ │
│  │  Session Persistence (SQLite)               │ │
│  └─────────────────────────────────────────────┘ │
│  Tauri 自动管理后端生命周期                      │
└───────────────────────────────────────────────────┘
```

---

## 🛠️ 开发运行

### 环境要求

| 工具 | 版本 |
|---|---|
| Node.js | >= 18 |
| Python | >= 3.10 |
| Rust | stable |

### 初始化

```powershell
# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖
cd web
npm install
cd ..
```

### 启动开发环境

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-dev.ps1
```

### 常用命令

```powershell
# 仅前端
cd web
npm run dev

# 仅后端
conda activate nowork
$env:PYTHONPATH = "server"
python -m app.run

# 完整桌面应用
npm run tauri:dev
```

---

## 📦 发布打包

```powershell
# 推荐方式
powershell -ExecutionPolicy Bypass -File scripts/build-release.ps1
```

产物目录：

```text
src-tauri/target/release/bundle/
```

### 打包说明

- 发布包会内置**嵌入式 Python 运行时**
- Python 依赖通过**allowlist 过滤复制**，不会打入整个 Conda 环境
- 终端用户**不需要**额外安装 Python、Conda 或手动安装依赖
- 服务端代码和资源会直接打进桌面应用中

---

## 📄 开源协议

[MIT License](LICENSE)
