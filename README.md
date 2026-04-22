<div align="center">

# Nowork

**A chat-style multi-agent desktop app. Each Agent / Team acts like a "contact" — click to start chatting.**

Build your own AI workforce — plan, code, review, debug, and document — all in one chat window.

[简体中文](./README.zh-CN.md)

</div>

---

## ✨ Highlights

| Feature | Description |
|---------|-------------|
| **Chat-as-a-Workspace** | Each Agent / Team is a "contact". Click to chat, just like Slack. No prompt engineering needed. |
| **Multi-Agent Teams** | Built-in team of 8 specialized workers: planning, coding, review, debugging, documentation, architecture. |
| **50+ Model Providers** | Powered by [Agno](https://github.com/agno-agi/agno). OpenAI, Anthropic, Google, DeepSeek, Qwen, Ollama, vLLM, and dozens more. One config, any model. |
| **Smart Context Management** | Automatic conversation compaction keeps long sessions alive without losing context. |
| **Secure Code Sandbox** | Sandboxed file/shell operations with per-session workspace isolation and read/write permissions. |
| **Document Processing** | Built-in skills for Word, Excel, PowerPoint, and PDF — create, edit, and analyze documents in chat. |
| **Scheduled Tasks** | Set daily/weekly recurring agent runs. Your agents work even when you're away. |
| **MCP Integration** | Connect external tool servers via Model Context Protocol. Extend your agents without code. |
| **Desktop-Native** | Tauri (Rust) shell with zero-config backend lifecycle. Install and run, no terminal needed. |
| **Bilingual UI** | English / 简体中文 with instant switching. Voice input via Web Speech API. |

## 🧠 Built-in Workers

| Worker | Role | Type |
|--------|------|------|
| Code Agent | Write, edit, and debug code | Agent |
| Planning Engineer | Analyze requirements, write implementation plans | Agent |
| Implementation Engineer | Execute plans step by step | Agent |
| Architecture Reviewer | Read-only code review and risk analysis | Agent |
| Code Explorer | Search, navigate, and understand codebases | Agent |
| Documentation Researcher | Write docs and research technical topics | Agent |
| Doc Agent | Create and process Office/PDF documents + web research | Agent |
| Product R&D Team | Full team: planner → coder → reviewer pipeline | Team |

> Workers are configured via YAML — add, remove, or customize without touching code.

## 🏗️ Architecture

```
┌─ Tauri Desktop (Rust) ─────────────────────────────┐
│                                                      │
│  ┌─ React Frontend (Vite + TypeScript) ───────────┐ │
│  │  NavRail │ Worker List │ Chat Workspace         │ │
│  │  Voice   │ Schedules   │ Settings │ Help        │ │
│  └────────────────────────────────────────────────┘ │
│                        HTTP / SSE                    │
│  ┌─ Python Backend (FastAPI) ────────────────────┐  │
│  │  Agno AgentOS ── Agent / Team / Workflow       │  │
│  │  CodingTools (sandboxed shell + file ops)      │  │
│  │  CompactionManager (smart context compression) │  │
│  │  MCP Client │ Knowledge Base │ Skills          │  │
│  │  Session Persistence (SQLite)                  │  │
│  └────────────────────────────────────────────────┘ │
│  Tauri auto-manages backend lifecycle               │
└──────────────────────────────────────────────────────┘
```

## 📸 Screenshots

> *Coming soon — see [docs/](docs/) for design documents.*

## 🚀 Quick Start

### 1. Model Provider

Create a model provider config file (e.g. OpenAI-compatible):

```yaml
# server/config/models/my-provider.yaml
provider_id: my-provider
name: My Provider
base_url: https://api.openai.com/v1      # or your self-hosted endpoint
api_key: sk-xxx
models:
  - id: gpt-4o
    name: GPT-4o
    image: true
    video: false
```

### 2. Default Model

```yaml
# server/config/config.yaml
default_model: my-provider/gpt-4o
```

### 3. Run

```powershell
# Install dependencies
pip install -r requirements.txt
cd web && npm install && cd ..

# Start dev environment
powershell -ExecutionPolicy Bypass -File scripts/start-dev.ps1
```

That's it. Open the app, pick a worker, and start chatting.

## ⚙️ Configuration

| File | Purpose |
|------|---------|
| `server/config/config.yaml` | Global config: default model, tools, server settings |
| `server/config/models/*.yaml` | Model provider definitions (API keys, endpoints, capabilities) |
| `server/config/workers/*.yaml` | Worker definitions: instructions, tools, workspaces, history |
| `server/config/mcp.yaml` | MCP server connections |

### Example Worker Config

```yaml
# server/config/workers/my-worker.yaml
agent:
  id: my-worker
  name: My Worker
  instructions: You are a helpful coding assistant.
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

## 🛠️ Development

### Prerequisites

| Tool | Version |
|------|---------|
| Node.js | >= 18 |
| Python | >= 3.10 |
| Rust | stable |

### Commands

```powershell
# Frontend
cd web && npm run dev          # Dev server with HMR

# Backend
conda activate nowork
$env:PYTHONPATH = "server"
python -m app.run              # Start at 127.0.0.1:18080

# Tauri desktop
npm run tauri:dev              # Full desktop dev mode
```

## 📦 Build & Package

```powershell
# One-step release build
npm run build:release

# Output: src-tauri/target/release/bundle/ (NSIS installer)
```


## 📄 License

[MIT License](LICENSE)
