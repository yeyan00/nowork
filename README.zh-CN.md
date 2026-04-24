<div align="center">

# Nowork

**聊天式多 Agent 桌面应用。每个 Agent / Team 就像一个「联系人」—— 点击即聊。**

组建你的 AI 工作团队 —— 规划、编码、审查、调试、文档，一个聊天窗口全搞定。

[English](./README.md)

</div>

---

## 🤔 为什么做 Nowork？

命令行 AI 编码工具功能强大，但交互门槛高。现有的桌面封装方案要么不够稳定，要么不够灵活。

Nowork 的思路不同：

- **桌面优先，不依赖终端** — 安装即用，无需命令行知识
- **聊天原生** — 每个 Agent 就是一个联系人，不用写 Prompt 模板，不用配置工作流，直接聊
- **轻量自包含** — 内置 Python 运行时，终端用户无需配置环境
- **面向个人和小团队** — 不追求大而全的平台，只做一个安静、可靠的工具

目标很简单：让 AI 处理重复性工作，把时间留给重要的事。

---

## ✨ 亮点

| 特性 | 说明 |
|------|------|
| **聊天即工作台** | 每个 Agent / Team 就是一个「联系人」。点击即聊，像用微信一样简单，无需写 Prompt。 |
| **多 Agent 团队** | 内置 8 个专职 Worker：规划、编码、审查、调试、文档、架构，开箱即用。 |
| **50+ 模型供应商** | 基于 [Agno](https://github.com/agno-agi/agno) 驱动。OpenAI、Anthropic、Google、DeepSeek、通义千问、Ollama、vLLM 等几十种模型，一个配置切换。 |
| **智能上下文管理** | 自动对话压缩（Compaction），长对话不爆上下文，关键信息不丢失。 |
| **安全沙箱** | 文件/Shell 操作受沙箱保护，支持会话级工作区隔离和读写权限控制。 |
| **文档处理** | 内置 Word、Excel、PPT、PDF 技能 —— 在聊天中直接创建、编辑、分析文档。 |
| **定时任务** | 设置每日/每周定时执行，让 Agent 在你不在时自动工作。 |
| **MCP 集成** | 通过 Model Context Protocol 连接外部工具服务器，零代码扩展 Agent 能力。 |
| **桌面原生** | Tauri (Rust) 外壳，后端进程零配置自动管理，安装即用，无需命令行。 |
| **双语界面** | English / 简体中文 随时切换，语音输入支持 Web Speech API。 |

## 🧠 内置 Worker

| Worker | 职责 | 类型 |
|--------|------|------|
| Code Agent | 编写、编辑、调试代码 | Agent |
| Planning Engineer | 需求分析、编写实施计划 | Agent |
| Implementation Engineer | 按计划逐步执行实现 | Agent |
| Architecture Reviewer | 只读代码审查与风险分析 | Agent |
| Code Explorer | 搜索、浏览、理解代码库 | Agent |
| Documentation Researcher | 编写文档、技术调研 | Agent |
| Doc Agent | Office/PDF 文档处理 + 网页调研 | Agent |
| Product R&D Team | 完整团队：规划 → 编码 → 审查 流水线 | Team |

> Worker 通过 YAML 配置 —— 无需改代码即可新增、删除或定制。

## 🏗️ 架构

```
┌─ Tauri 桌面端 (Rust) ──────────────────────────────┐
│                                                      │
│  ┌─ React 前端 (Vite + TypeScript) ───────────────┐ │
│  │  导航栏 │ Worker 列表 │ 聊天工作区              │ │
│  │  语音   │ 定时任务   │ 设置  │ 帮助             │ │
│  └────────────────────────────────────────────────┘ │
│                        HTTP / SSE                    │
│  ┌─ Python 后端 (FastAPI) ────────────────────────┐ │
│  │  Agno AgentOS ── Agent / Team / Workflow        │ │
│  │  CodingTools (沙箱 Shell + 文件操作)            │ │
│  │  CompactionManager (智能上下文压缩)             │ │
│  │  MCP 客户端 │ 知识库 │ Skills                   │ │
│  │  会话持久化 (SQLite)                            │ │
│  └─────────────────────────────────────────────────┘ │
│  Tauri 自动管理后端进程生命周期                       │
└──────────────────────────────────────────────────────┘
```

## 📸 截图

> *即将更新 —— 设计文档见 [docs/](docs/)。*

## ⚠️ Agno 依赖说明

Nowork 核心依赖 [Agno](https://github.com/agno-agi/agno) 作为 Agent 框架。由于部分自定义修改尚未合入上游，目前使用 fork 版本：

**https://github.com/yeyan00/agno**

安装方式：

```bash
pip install git+https://github.com/yeyan00/agno.git
```

> 待上游合入相关改动或不再需要这些补丁后，会切回官方版本。

## 🚀 快速开始

### 1. 配置模型供应商

创建模型供应商配置文件（以 OpenAI 兼容接口为例）：

```yaml
# server/config/models/my-provider.yaml
provider_id: my-provider
name: 我的供应商
base_url: https://api.openai.com/v1      # 或你的自建接口
api_key: sk-xxx
models:
  - id: gpt-4o
    name: GPT-4o
    image: true
    video: false
```

### 2. 设置默认模型

```yaml
# server/config/config.yaml
default_model: my-provider/gpt-4o
```

### 3. 启动

```powershell
# 安装依赖
pip install -r requirements.txt
cd web && npm install && cd ..

# 启动开发环境
powershell -ExecutionPolicy Bypass -File scripts/start-dev.ps1
```

完成。打开应用，选择一个 Worker，开始聊天。

## ⚙️ 配置

| 文件 | 用途 |
|------|------|
| `server/config/config.yaml` | 全局配置：默认模型、工具、服务设置 |
| `server/config/models/*.yaml` | 模型供应商定义（API Key、接口、能力） |
| `server/config/workers/*.yaml` | Worker 定义：指令、工具、工作区、历史 |
| `server/config/mcp.yaml` | MCP 服务器连接 |

### Worker 配置示例

```yaml
# server/config/workers/my-worker.yaml
agent:
  id: my-worker
  name: My Worker
  instructions: 你是一个有用的编程助手。
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

## 🛠️ 开发

### 环境要求

| 工具 | 版本 |
|------|------|
| Node.js | >= 18 |
| Python | >= 3.10 |
| Rust | stable |

### 命令

```powershell
# 前端
cd web && npm run dev          # 开发服务器（HMR）

# 后端
conda activate nowork
$env:PYTHONPATH = "server"
python -m app.run              # 启动，默认 127.0.0.1:18080

# Tauri 桌面端
npm run tauri:dev              # 完整桌面开发模式
```

## 📦 构建与打包

```powershell
# 一键发布构建
npm run build:release

# 产物：src-tauri/target/release/bundle/（NSIS 安装程序）
```


## 📄 开源协议

[MIT License](LICENSE)
