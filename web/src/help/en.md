# NoWork User Guide

## Getting Started

Welcome to NoWork! Follow these three steps to get started:

### Step 1: Configure a Model Provider

> ⚠️ **This is the required first step.** Without a configured model, no Worker can run.

1. Click **Models** in the left navigation rail
2. Click **+ Add Provider** in the left sidebar list
3. Fill in the following fields:

| Field | Description | Example |
|-------|-------------|---------|
| **Provider ID** | Unique identifier (lowercase, hyphens) | `qwen-coding` |
| **Name** | Display name | `Qwen Coding` |
| **Type** | Protocol type (currently OpenAI Compatible) | Keep default |
| **Base URL** | API base endpoint | `https://api.openai.com/v1` |
| **API Key** | Your API key | `sk-xxxxx` |

4. Click **Fetch from API** to auto-discover available models, or click **+ Add Model** to add manually
5. For each model, configure:
   - **Model ID**: Local identifier (e.g., `gpt-4o`)
   - **Name**: Display name
   - **Image**: Whether the model supports image input
   - **Video**: Whether the model supports video input
6. Click **Save**

**Common API Endpoints:**

| Provider | Base URL |
|----------|----------|
| OpenAI | `https://api.openai.com/v1` |
| Alibaba Cloud (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Zhipu (GLM) | `https://open.bigmodel.cn/api/paas/v4` |
| Moonshot | `https://api.moonshot.cn/v1` |

> 💡 **Tip:** You can also edit config files directly. Model configs live in `server/config/models/` — see `*.example.yaml` for templates.

### Step 2: Set the Default Model

Edit `server/config/config.yaml` and make sure `default_model` points to your configured model:

```yaml
default_model: qwen-coding/qwen3.6-plus
```

The format is `{Provider ID}/{Model ID}`. Save and restart the server.

> 💡 **Tip:** All Workers without an explicitly assigned model will use this default.

### Step 3: Start Chatting

1. Click **Chat** in the left navigation rail
2. Select a Worker from the left sidebar (e.g., Code Agent)
3. Type a message in the composer at the bottom and press Enter
4. The Worker will stream its response in real time

---

## Core Features

### 💬 Chat

**Session Management:**
- Click the **+** button to create a new session
- Session tabs show timestamps — click to switch between sessions
- Each session maintains its own conversation context

**Workspace Selection:**
- The folder button on the left side of the composer lets you choose which directories the current session can access
- `All` means the session uses all Worker-configured directories
- Selecting specific directories restricts the Worker's file access to only those paths

**Attachments:**
- 📎 **File**: Attach code/text files
- 🖼️ **Image**: Attach screenshots (requires model with Image support)
- 🎬 **Video**: Attach video clips (requires model with Video support)
- 🎤 **Voice**: Click the microphone button for speech-to-text input (requires browser support)

**Worker Settings:**
- Click the ⚙ gear icon in the chat header to open a settings sidebar for the current Worker
- You can modify the system prompt, model, tools, and other configuration

**Token Usage:**
- Below the chat area, context and output token counts are displayed in real time
- This helps monitor token consumption during long conversations

**Team Member Activities:**
- When chatting with a **Team** Worker, a 👥 button appears in the chat header
- Click it to open the Member Activity sidebar, which shows each member agent's progress in real time
- Each member section can be expanded to view output content and tool call details
- The tool list within each member section can be collapsed independently

### 👷 Workers

Workers are the core execution units in NoWork. They can be:
- **Agent**: A single agent performing independent tasks
- **Team**: Multiple agents collaborating
- **Workflow**: Process orchestration

**Creating / Editing a Worker:**
1. Go to the Workers page
2. Select the Agent / Team / Workflow tab
3. Click a Worker in the list to edit it

**Worker Configuration Sections:**

| Section | Description |
|---------|-------------|
| **Basic** | Name, description, system instructions |
| **Model** | Choose the provider and specific model for this Worker |
| **Tools** | Enable/disable available tools (e.g., CodingTools) |
| **Workspace** | Configure accessible directories and permissions (read-write / read-only) |
| **MCP Servers** | Bind Model Context Protocol servers |
| **Knowledge Bases** | Bind vector knowledge bases |
| **Skills** | Enable/disable available skills |
| **Learning** | View and manage user profile and memory data |
| **Members** | Manage multi-agent members (Team type) |

### ⏰ Schedules

Schedules let you automatically trigger a Worker at specified times.

**Creating a Schedule:**
1. Go to the Schedules page
2. Click **New Schedule**
3. Configure:
   - **Name**: Schedule name (e.g., "Daily Summary")
   - **Worker**: The Worker to trigger
   - **Trigger**: Trigger type
     - `Daily`: Every day at a fixed time
     - `Weekly`: On specific weekdays at a fixed time
   - **Time**: Trigger time (HH:mm)
   - **Prompt**: The prompt sent to the Worker when triggered
   - **Misfire Policy**: What happens if the schedule was missed
     - `Run once when app returns`: Execute once when the app comes back
     - `Skip missed run`: Skip the missed execution

**Run History:**
- The bottom panel shows past executions
- Includes status (Success/Failed), planned time, and linked session
- Click **Open Worker Chat** to jump to the associated session

> ⚠️ **Note:** Schedules require the application to be running in order to fire.

### 📚 Skills

Skills are reusable prompt packages that enhance Worker capabilities.

- Browse installed skills
- Click a skill to view its details (SKILL.md content)
- Install new skills via **Install Skill** (local directory path or URL)

### 📖 Knowledge Bases

Knowledge Bases let you build structured, searchable Wiki from your documents. Workers can query knowledge bases during conversations to provide context-aware answers.

**Creating a Knowledge Base:**
1. Click **Knowledge** in the left navigation rail
2. Click **+ Create** in the top-right corner
3. Enter a name for the knowledge base
4. Optionally enable **Wiki Mode** (recommended) — this creates a Wiki-style knowledge base with auto-ingest, full-text search, and knowledge graph visualization
5. Click **Create**

**Configuring a Knowledge Base:**

| Setting | Description |
|---------|-------------|
| **Name** | Display name for the knowledge base |
| **Description** | Brief description of the knowledge base purpose |
| **Wiki Mode** | Enable Wiki-style knowledge management (recommended) |
| **Purpose** | Describe the knowledge base's goal — this guides the AI during auto-ingest to generate relevant Wiki pages |
| **Auto Sync** | Automatically sync files on app startup |
| **Paths** | Directories or files to ingest (one per line) |

**Wiki Mode Features:**

- **Pages Tab**: Browse all generated Wiki pages by type (entities, concepts, sources, queries). Click a page to read its content, edit, or delete it.
- **Sync**: Click **Sync** to ingest new or changed files from your configured paths. The AI will analyze documents and generate structured Wiki pages (entities, concepts, source summaries).
- **Search Tab**: Full-text search across all Wiki pages. Results show title matches, content snippets, and relevance.
- **Knowledge Graph**: Visualize relationships between Wiki pages. Nodes represent pages, edges represent cross-references (`[[wikilinks]]`).
- **Page Editor**: Edit any Wiki page's raw Markdown content directly within the app.

**Traditional Vector Mode:**

If Wiki Mode is disabled, the knowledge base uses traditional vector embedding and similarity search instead. Configure the paths to your documents, then click **Reload** to index them.

**Binding a Knowledge Base to a Worker:**
1. Go to **Workers** → select a Worker
2. Scroll to the **Knowledge Bases** section
3. Select one or more knowledge bases to bind
4. The Worker will automatically gain a `search_knowledge` tool to query the bound knowledge bases during conversations

### 🧩 Extensions

Manage optional extension packages:
- **Embedding Models**: Text embedding models (used by knowledge bases)
- **Vector Databases**: Vector database drivers

### 🔌 MCP Servers

Configure Model Context Protocol server connections to provide Workers with external tools and data sources.

### ⚙️ Settings

- **Language**: Switch between English and Chinese interface
- **Session Compaction**: Configure automatic conversation context management
  - **Enable**: Turn compaction on or off
  - **Context Usage Threshold**: Trigger compaction when context usage reaches this percentage (e.g., 80%)
  - **Reserve Tokens**: Number of tokens to keep free after compaction
  - **Preserve Recent Messages**: Number of recent messages to keep unsummarized
  - **Max Injected Summaries**: Maximum number of past summaries injected into the context
- **Version**: View current version and check for updates
- **License**: View the MIT License

---

## Configuration Reference

### Directory Structure

```
server/config/
├── config.yaml              # Main config (API keys, default model, etc.)
├── models/                  # Model provider configs
│   ├── *.example.yaml       # Template files (committed to Git)
│   └── *.yaml               # Actual configs (in .gitignore)
└── workers/                 # Worker configs
    └── *.yaml               # Individual Worker config files
```

### config.yaml Key Fields

```yaml
server:
  host: 127.0.0.1
  port: 18080
default_model: provider-id/model-id   # Default model
models:
  - provider-id                        # Enabled provider list
workers:
  - worker-name                        # Enabled Worker list
```

### Model Provider Config (models/*.yaml)

```yaml
provider: openai
name: Display Name
type: openai_compatible
base_url: https://api.example.com/v1
api_key: YOUR_API_KEY
models:
  model-id:
    name: Display Name
    image: true    # Supports image input
    video: false   # Supports video input
```

---

## FAQ

### Q: Worker returns "default_model not configured" error
**A:** Edit `server/config/config.yaml`, add or update `default_model: provider-id/model-id`, then restart the server.

### Q: Worker cannot access files
**A:** Check the `workspaces` section in the Worker config. Make sure the target directory is listed with the correct permission (read-write).

### Q: Scheduled tasks are not running
**A:** Schedules require the application to be running. Check that the schedule is Enabled and the time is set correctly.

### Q: Voice input is not available
**A:** Voice input uses the browser's built-in Web Speech API, which requires a Chromium-based browser or WebView2. Make sure microphone permissions are granted.

### Q: How do I add a new model provider?
**A:** Go to Models → + Add Provider → fill in Provider ID, Base URL, API Key → Fetch from API or add models manually → Save.

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift + Enter` | New line |
