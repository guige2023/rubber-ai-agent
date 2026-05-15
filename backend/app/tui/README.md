# RabAi Agent TUI

Terminal User Interface (TUI) for RabAi Agent - similar to OpenCLAW's TUI.

## Features

- **Chat Interface**: Send messages to the agent and receive responses
- **Session Management**: Create, switch, and delete chat sessions
- **System Status**: View system status and running tasks
- **Keyboard Shortcuts**: Navigate command history and more

## Quick Start

### 1. Start the Backend Server

In one terminal:

```bash
cd backend
conda run -n rabaiagent python -m app.sidecar
```

Or if you have the environment activated:

```bash
cd backend
python -m app.sidecar
```

### 2. Start the TUI

In another terminal:

```bash
cd backend
conda run -n rabaiagent python -m app.tui
```

Or with custom gateway URL and token:

```bash
python -m app.tui --gateway ws://127.0.0.1:8000/ws --token your-token-here
```

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/new` | Create a new session |
| `/sessions` | List all sessions |
| `/switch <id>` | Switch to a session |
| `/delete <id>` | Delete a session |
| `/clear` | Clear the chat log |
| `/status` | Show system status |
| `/tasks` | List running tasks |

## Keyboard Shortcuts

| Shortcut | Description |
|----------|-------------|
| `Ctrl+C` | Exit |
| `Ctrl+L` | Clear screen |
| `Ctrl+H` | Toggle help |
| `Ctrl+N` | New session |
| `↑` / `↓` | Navigate command history |

## Architecture

The TUI connects to the backend via WebSocket, similar to OpenCLAW's Gateway mode:

```
┌─────────────────────────────────────────┐
│              TUI (Textual)              │
│  ┌─────────┐  ┌──────────────────┐     │
│  │ Sessions │  │    Chat Log      │     │
│  │  Tree    │  │   + Input        │     │
│  └────┬────┘  └────────┬─────────┘     │
│       │                │               │
│       │   TuiGatewayClient            │
│       └────────┬───────┘               │
│                │                       │
└────────────────┼───────────────────────┘
                 │ WebSocket
                 ▼
┌─────────────────────────────────────────┐
│         Backend (RabAiAgent)              │
│  ┌──────────────┐  ┌───────────────┐   │
│  │ WebSocket   │  │   Agent       │   │
│  │  Endpoint   │  │   Runtime     │   │
│  └──────────────┘  └───────────────┘   │
└─────────────────────────────────────────┘
```

## Dependencies

- `textual>=1.0.0` - Modern TUI framework for Python
- `websockets` - WebSocket client (already in requirements)
