"""
RabAi Agent TUI Application - Main terminal UI.

A terminal-based UI for interacting with the RabAi Agent,
similar to OpenCLAW's TUI.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import Mount
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Static,
    RichLog,
    Tree,
)

from app.tui.gateway_client import SessionInfo, TuiEvent, TuiGatewayClient

logger = logging.getLogger(__name__)


class ChatLog(Vertical):
    """Chat message display widget."""

    def __init__(self) -> None:
        super().__init__()
        self._log: Optional[RichLog] = None

    def compose(self) -> ComposeResult:
        self._log = RichLog(id="chat-log", wrap=True, max_lines=500)
        yield self._log

    def append_user(self, text: str) -> None:
        if self._log:
            self._log.write(f"[bold blue]You:[/bold blue] {text}")

    def append_agent(self, text: str) -> None:
        if self._log:
            self._log.write(f"[bold green]Agent:[/bold green] {text}")

    def append_system(self, text: str) -> None:
        if self._log:
            self._log.write(f"[dim]{text}[/dim]")

    def clear(self) -> None:
        if self._log:
            self._log.clear()


class SessionTree(Tree):
    """Session list sidebar."""

    def __init__(self) -> None:
        super().__init__("Sessions", id="session-tree")
        self._sessions: list[SessionInfo] = []

    def set_sessions(self, sessions: list[SessionInfo]) -> None:
        self._sessions = sessions
        self.clear()
        for session in sessions:
            self.add_leaf(f"📝 {session.title or 'Untitled'}", data=session)

    def get_selected_session(self) -> Optional[SessionInfo]:
        """Get the currently selected session."""
        node = self.cursor_node
        if node and node.data:
            return node.data
        return None


class StatusBar(Horizontal):
    """Status bar showing connection status and info."""

    def __init__(self) -> None:
        super().__init__(id="status-bar")
        self._status = Static("Connecting...", id="status-text")
        self._tokens = Static("", id="token-count")

    def compose(self) -> ComposeResult:
        yield self._status
        yield self._tokens

    def set_status(self, text: str, color: str = "white") -> None:
        self._status.update(f"[{color}]{text}[/{color}]")

    def set_tokens(self, input_tokens: int, output_tokens: int) -> None:
        total = input_tokens + output_tokens
        self._tokens.update(f"Tokens: {total:,} (in: {input_tokens:,}, out: {output_tokens:,})")


class TuiInput(Input):
    """Command input with history."""

    def __init__(self) -> None:
        super().__init__(placeholder="Type a message or /help for commands...", id="command-input")
        self._history: list[str] = []
        self._history_index: int = -1

    def push_history(self, text: str) -> None:
        if text.strip() and (not self._history or self._history[0] != text):
            self._history.insert(0, text)
            if len(self._history) > 100:
                self._history.pop()
        self._history_index = -1

    def history_up(self) -> None:
        if self._history and self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.value = self._history[self._history_index]

    def history_down(self) -> None:
        if self._history_index > 0:
            self._history_index -= 1
            self.value = self._history[self._history_index]
        elif self._history_index == 0:
            self._history_index = -1
            self.value = ""


class ChatScreen(Container):
    """Main chat screen."""

    def __init__(self, app: "TuiApplication") -> None:
        super().__init__()
        self._app = app
        self._chat_log = ChatLog()
        self._input = TuiInput()
        self._sessions = SessionTree()

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="sidebar", classes="sidebar"):
                yield self._sessions
                with Vertical(id="sidebar-actions"):
                    yield Button("New Session", id="btn-new-session", variant="primary")
                    yield Button("Delete", id="btn-delete-session", variant="error")
            with Vertical(id="main-content"):
                with Vertical(id="chat-area"):
                    yield self._chat_log
                yield self._input

    def on_mount(self) -> None:
        """Initialize the screen."""
        self._chat_log.append_system("Welcome to RabAi Agent TUI!")
        self._chat_log.append_system("Type /help for available commands.")

    async def on_input_submitted(self, event: TuiInput.Submitted) -> None:
        """Handle input submission."""
        text = event.value.strip()
        if not text:
            return

        self._input.push_history(text)
        self._input.value = ""

        if text.startswith("/"):
            await self._app.handle_command(text)
        else:
            await self._app.send_message(text)

    def key_up(self) -> None:
        """Handle history up."""
        self._input.history_up()

    def key_down(self) -> None:
        """Handle history down."""
        self._input.history_down()


class HelpOverlay(Container):
    """Help overlay showing available commands."""

    def compose(self) -> ComposeResult:
        yield Static(
            """
[bold]RabAi Agent TUI - Help[/bold]

[bold]Commands:[/bold]
  /help              - Show this help
  /new               - Create a new session
  /sessions          - List all sessions
  /switch <id>       - Switch to a session
  /delete <id>       - Delete a session
  /clear             - Clear the chat log
  /status            - Show system status
  /tasks             - List running tasks

[bold]Keyboard Shortcuts:[/bold]
  Ctrl+C             - Exit
  Ctrl+L             - Clear screen
  ↑/↓               - Navigate command history
  Tab                - (future) Autocomplete

[bold]Gateway:[/bold]
  Connected to: {gateway_url}
            """.strip(),
            id="help-content",
        )
        yield Button("Close", id="btn-close-help")


class TuiApplication(App):
    """
    Main TUI Application for RabAi Agent.

    Provides a terminal UI similar to OpenCLAW's TUI for:
    - Chat interaction with the agent
    - Session management
    - System monitoring
    """

    CSS = """
    Screen {
        background: $surface;
    }

    #sidebar {
        width: 25%;
        background: $panel;
        border-right: solid $border;
    }

    #sidebar-actions {
        height: auto;
        padding: 1;
        layout: grid;
        grid-size: 2;
        gap: 1;
    }

    #main-content {
        width: 75%;
    }

    #chat-area {
        height: 1fr;
        padding: 1;
    }

    #chat-log {
        background: $surface;
        border: solid $border;
        padding: 1;
    }

    #command-input {
        dock: bottom;
        margin: 1;
    }

    #status-bar {
        height: 1;
        background: $panel;
        padding: 0 1;
        content-align: center middle;
    }

    #help-overlay {
        align: center middle;
        background: $surface 80%;
        padding: 3;
        border: solid $accent;
    }

    Button {
        margin: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "exit", "Exit", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("ctrl+h", "toggle_help", "Help", show=True),
        Binding("ctrl+n", "new_session", "New Session", show=True),
        Binding("up", "history_up", "History Up", show=False),
        Binding("down", "history_down", "History Down", show=False),
    ]

    def __init__(
        self,
        gateway_url: str = "ws://127.0.0.1:8000/ws",
        token: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._gateway_url = gateway_url
        self._token = token or os.environ.get("FERRYMAN_BEARER_TOKEN", "dev-token")
        self._client: Optional[TuiGatewayClient] = None
        self._current_session: Optional[SessionInfo] = None
        self._chat_screen: Optional[ChatScreen] = None
        self._help_visible = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield ChatScreen(self)
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the TUI."""
        self.title = "RabAi Agent TUI"
        asyncio.create_task(self._connect_gateway())

    async def _connect_gateway(self) -> None:
        """Connect to the gateway."""
        try:
            self._client = TuiGatewayClient(
                url=self._gateway_url,
                token=self._token,
            )
            await self._client.connect()
            self._client.on_event(self._handle_event)

            # Update status
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_status("Connected to gateway", "green")

            # Load sessions
            await self._refresh_sessions()

            # Show welcome message
            if self._chat_screen:
                self._chat_screen._chat_log.append_system(
                    f"Connected! Gateway: {self._gateway_url}"
                )

        except Exception as e:
            logger.error(f"Failed to connect to gateway: {e}")
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_status(f"Connection failed: {e}", "red")

    async def _handle_event(self, event: TuiEvent) -> None:
        """Handle gateway events."""
        if event.namespace == "agent" and event.event == "chat_final":
            if self._chat_screen:
                payload = event.payload or {}
                messages = payload.get("messages", [])
                for msg in messages:
                    if msg.get("role") == "assistant":
                        content = msg.get("content", "")
                        self._chat_screen._chat_log.append_agent(content)
        elif event.namespace == "agent" and event.event == "tool_activity":
            if self._chat_screen:
                tool_name = event.payload.get("tool_name", "unknown") if event.payload else "unknown"
                phase = event.payload.get("phase", "") if event.payload else ""
                self._chat_screen._chat_log.append_system(f"[Tool: {tool_name} ({phase})]")

    async def _refresh_sessions(self) -> None:
        """Refresh the session list."""
        if not self._client or not self._client.is_connected:
            return

        try:
            sessions = await self._client.list_sessions()
            if self._chat_screen:
                self._chat_screen._sessions.set_sessions(sessions)
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    async def send_message(self, text: str) -> None:
        """Send a message to the agent."""
        if not self._client or not self._client.is_connected:
            self._push_error("Not connected to gateway")
            return

        # Ensure we have a session
        if not self._current_session:
            try:
                session = await self._client.create_session()
                self._current_session = session
                await self._refresh_sessions()
            except Exception as e:
                self._push_error(f"Failed to create session: {e}")
                return

        # Show user message
        if self._chat_screen:
            self._chat_screen._chat_log.append_user(text)

        # Send to gateway
        try:
            result = await self._client.execute(text, self._current_session.id)
            if result.get("status") == "started":
                run_id = result.get("run_id")
                if self._chat_screen:
                    self._chat_screen._chat_log.append_system(f"Running... (run_id: {run_id})")
            else:
                self._push_error(f"Execute failed: {result.get('message', 'Unknown error')}")
        except Exception as e:
            self._push_error(f"Send failed: {e}")

    def _push_error(self, text: str) -> None:
        """Push an error message to the chat log."""
        if self._chat_screen:
            self._chat_screen._chat_log.append_system(f"[bold red]Error:[/bold red] {text}")

    async def handle_command(self, cmd: str) -> None:
        """Handle a slash command."""
        parts = cmd.split()
        command = parts[0].lower()
        args = parts[1:]

        if command == "/help":
            self.action_toggle_help()
        elif command == "/new":
            await self._cmd_new_session()
        elif command == "/sessions":
            await self._cmd_list_sessions()
        elif command == "/switch":
            await self._cmd_switch(args)
        elif command == "/delete":
            await self._cmd_delete(args)
        elif command == "/clear":
            if self._chat_screen:
                self._chat_screen._chat_log.clear()
        elif command == "/status":
            await self._cmd_status()
        elif command == "/tasks":
            await self._cmd_tasks()
        else:
            self._push_error(f"Unknown command: {command}")

    async def _cmd_new_session(self) -> None:
        """Create a new session."""
        if not self._client or not self._client.is_connected:
            self._push_error("Not connected to gateway")
            return

        try:
            session = await self._client.create_session()
            self._current_session = session
            await self._refresh_sessions()
            if self._chat_screen:
                self._chat_screen._chat_log.append_system(f"Created new session: {session.id}")
        except Exception as e:
            self._push_error(f"Failed to create session: {e}")

    async def _cmd_list_sessions(self) -> None:
        """List all sessions."""
        if not self._client or not self._client.is_connected:
            self._push_error("Not connected to gateway")
            return

        try:
            sessions = await self._client.list_sessions()
            if self._chat_screen:
                self._chat_screen._chat_log.append_system("Sessions:")
                for s in sessions:
                    marker = " [current]" if self._current_session and s.id == self._current_session.id else ""
                    self._chat_screen._chat_log.append_system(
                        f"  {s.id}: {s.title or 'Untitled'}{marker}"
                    )
        except Exception as e:
            self._push_error(f"Failed to list sessions: {e}")

    async def _cmd_switch(self, args: list[str]) -> None:
        """Switch to a session."""
        if not args:
            self._push_error("Usage: /switch <session_id>")
            return

        session_id = args[0]
        if not self._client or not self._client.is_connected:
            self._push_error("Not connected to gateway")
            return

        try:
            sessions = await self._client.list_sessions()
            for s in sessions:
                if s.id == session_id:
                    self._current_session = s
                    if self._chat_screen:
                        self._chat_screen._chat_log.clear()
                        self._chat_screen._chat_log.append_system(f"Switched to session: {s.title}")
                    return

            self._push_error(f"Session not found: {session_id}")
        except Exception as e:
            self._push_error(f"Failed to switch session: {e}")

    async def _cmd_delete(self, args: list[str]) -> None:
        """Delete a session."""
        if not args:
            self._push_error("Usage: /delete <session_id>")
            return

        session_id = args[0]
        if not self._client or not self._client.is_connected:
            self._push_error("Not connected to gateway")
            return

        try:
            await self._client.delete_session(session_id)
            if self._current_session and self._current_session.id == session_id:
                self._current_session = None
            await self._refresh_sessions()
            if self._chat_screen:
                self._chat_screen._chat_log.append_system(f"Deleted session: {session_id}")
        except Exception as e:
            self._push_error(f"Failed to delete session: {e}")

    async def _cmd_status(self) -> None:
        """Show system status."""
        if not self._client or not self._client.is_connected:
            self._push_error("Not connected to gateway")
            return

        try:
            status = await self._client.get_system_status()
            if self._chat_screen:
                self._chat_screen._chat_log.append_system("System Status:")
                for key, value in status.items():
                    self._chat_screen._chat_log.append_system(f"  {key}: {value}")
        except Exception as e:
            self._push_error(f"Failed to get status: {e}")

    async def _cmd_tasks(self) -> None:
        """List running tasks."""
        if not self._client or not self._client.is_connected:
            self._push_error("Not connected to gateway")
            return

        try:
            tasks = await self._client.list_tasks()
            if self._chat_screen:
                self._chat_screen._chat_log.append_system("Running Tasks:")
                if not tasks:
                    self._chat_screen._chat_log.append_system("  (none)")
                for task in tasks:
                    self._chat_screen._chat_log.append_system(
                        f"  {task.get('id', '?')}: {task.get('title', 'Untitled')} [{task.get('status', '?')}]"
                    )
        except Exception as e:
            self._push_error(f"Failed to list tasks: {e}")

    def action_exit(self) -> None:
        """Exit the application."""
        asyncio.create_task(self._cleanup())
        self.exit()

    async def _cleanup(self) -> None:
        """Cleanup on exit."""
        if self._client:
            await self._client.disconnect()

    def action_clear(self) -> None:
        """Clear the screen."""
        if self._chat_screen:
            self._chat_screen._chat_log.clear()

    def action_toggle_help(self) -> None:
        """Toggle help overlay."""
        self._help_visible = not self._help_visible
        help_el = self.query_one("#help-overlay", HelpOverlay) if self._help_visible else None
        if help_el:
            help_el.display = True
        elif self._help_visible:
            # Need to create help overlay
            pass

    def action_new_session(self) -> None:
        """Create a new session."""
        asyncio.create_task(self._cmd_new_session())

    def action_history_up(self) -> None:
        """Navigate command history up."""
        if self._chat_screen:
            self._chat_screen.key_up()

    def action_history_down(self) -> None:
        """Navigate command history down."""
        if self._chat_screen:
            self._chat_screen.key_down()


async def run_tui(
    gateway_url: str = "ws://127.0.0.1:8000/ws",
    token: Optional[str] = None,
) -> None:
    """Run the TUI application."""
    app = TuiApplication(gateway_url=gateway_url, token=token)
    await app.run_async()


def main() -> None:
    """Main entry point for the TUI."""
    import argparse

    parser = argparse.ArgumentParser(description="RabAi Agent TUI")
    parser.add_argument(
        "--gateway",
        default=os.environ.get("FERRYMAN_WS_URL", "ws://127.0.0.1:8000/ws"),
        help="Gateway WebSocket URL",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("FERRYMAN_BEARER_TOKEN"),
        help="Bearer token for authentication",
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(run_tui(gateway_url=args.gateway, token=args.token))


if __name__ == "__main__":
    main()
