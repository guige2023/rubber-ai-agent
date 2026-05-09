from pydantic_ai.messages import BinaryImage
from pydantic_ai.tools import RunContext
from app.core.browser import BrowserActionError
from app.core.deps import AgentDeps, get_browser_manager, get_workspace
from app.core.tool_errors import RetryableToolError
from app.core.toolkits.base import Toolkit
from typing import Optional

BROWSER_ACTION_ERROR_TYPE = "browser_action_error"


async def _run_browser_action(action):
    try:
        return await action()
    except BrowserActionError as e:
        raise RetryableToolError(str(e), error_type=BROWSER_ACTION_ERROR_TYPE) from e


class WebToolkit(Toolkit):
    """Browser tools for page navigation, inspection, interaction, and capture."""

    @staticmethod
    async def _get_browser(ctx: RunContext[AgentDeps], headless: Optional[bool] = None):
        try:
            browser_manager = get_browser_manager(ctx.deps)
            return await browser_manager.get_browser(ctx.deps.session_id, headless=headless)
        except RuntimeError as e:
            raise RetryableToolError(str(e), error_type=BROWSER_ACTION_ERROR_TYPE) from e

    @staticmethod
    def get_tools():
        return [
            WebToolkit.browser_navigate,
            WebToolkit.browser_get_distilled_dom,
            WebToolkit.browser_aria_snapshot,
            WebToolkit.browser_click,
            WebToolkit.browser_type,
            WebToolkit.browser_scroll,
            WebToolkit.browser_wait,
            WebToolkit.browser_console,
            WebToolkit.browser_screenshot,
        ]

    @staticmethod
    async def browser_navigate(
        ctx: RunContext[AgentDeps],
        url: str,
        headless: Optional[bool] = None,
        include_snapshot: bool = False,
    ) -> dict[str, object]:
        """Open a URL and return lightweight page status.

        Set `headless=False` when the browser should stay visible to the user.
        Set `include_snapshot=True` only when you immediately need clickable
        or typeable element IDs; otherwise call `browser_aria_snapshot` later.
        """
        browser = await WebToolkit._get_browser(ctx, headless=headless)
        return await _run_browser_action(lambda: browser.navigate(url, include_snapshot=include_snapshot))

    @staticmethod
    async def browser_get_distilled_dom(ctx: RunContext[AgentDeps]) -> str:
        """Extract readable page text for analysis.

        Best for article or content reading, not precise interaction targeting.
        """
        browser = await WebToolkit._get_browser(ctx)
        return await _run_browser_action(browser.get_distilled_dom)

    @staticmethod
    async def browser_click(ctx: RunContext[AgentDeps], selector: str) -> str:
        """Click an element in the current page.

        Accepts a selector. IDs from `browser_aria_snapshot` are recommended
        for stability.
        """
        browser = await WebToolkit._get_browser(ctx)
        return await _run_browser_action(lambda: browser.click(selector))

    @staticmethod
    async def browser_type(ctx: RunContext[AgentDeps], selector: str, text: str) -> str:
        """Type into an element in the current page.

        Accepts a selector. IDs from `browser_aria_snapshot` are recommended
        for stability.
        """
        browser = await WebToolkit._get_browser(ctx)
        return await _run_browser_action(lambda: browser.type(selector, text))

    @staticmethod
    async def browser_aria_snapshot(ctx: RunContext[AgentDeps]) -> str:
        """Return an accessibility snapshot with stable IDs for later interactions."""
        browser = await WebToolkit._get_browser(ctx)
        return await _run_browser_action(browser.get_aria_snapshot)

    @staticmethod
    async def browser_scroll(
        ctx: RunContext[AgentDeps],
        direction: str = "down",
        selector: Optional[str] = None,
    ) -> str:
        """Scroll the page up or down, or scroll an element into view."""
        browser = await WebToolkit._get_browser(ctx)
        return await _run_browser_action(lambda: browser.scroll(direction=direction, selector=selector))

    @staticmethod
    async def browser_wait(
        ctx: RunContext[AgentDeps],
        timeout_ms: int = 2000,
        selector: Optional[str] = None,
    ) -> str:
        """Wait for time to pass or for a selector to appear."""
        browser = await WebToolkit._get_browser(ctx)
        return await _run_browser_action(lambda: browser.wait(timeout_ms, selector=selector))

    @staticmethod
    async def browser_console(ctx: RunContext[AgentDeps], clear: bool = False) -> str:
        """Return recent browser console messages and page errors."""
        browser = await WebToolkit._get_browser(ctx)
        return await _run_browser_action(lambda: browser.get_console_messages(clear=clear))

    @staticmethod
    async def browser_screenshot(
        ctx: RunContext[AgentDeps],
        selector: Optional[str] = None,
        max_image_side: int = 1536,
        quality: int = 80,
    ) -> BinaryImage:
        """Capture a compressed JPEG page or element screenshot.

        The screenshot is scaled so its longest side is at most `max_image_side`
        pixels before being returned as `BinaryImage`.
        """
        browser = await WebToolkit._get_browser(ctx)
        screenshot_dir = get_workspace(ctx.deps) / "screenshots"
        return await _run_browser_action(
            lambda: browser.screenshot(
                selector,
                output_dir=screenshot_dir,
                max_image_side=max_image_side,
                quality=quality,
            )
        )
