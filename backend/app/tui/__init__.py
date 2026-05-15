"""
RabAi Agent TUI - Terminal User Interface

Provides a terminal-based UI for interacting with the RabAi Agent,
similar to OpenCLAW's TUI.
"""

from app.tui.app import TuiApplication
from app.tui.gateway_client import TuiGatewayClient

__all__ = ["TuiApplication", "TuiGatewayClient"]
