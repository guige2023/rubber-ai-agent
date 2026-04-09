from pydantic_ai.messages import BinaryImage
from pydantic_ai.tools import RunContext
from app.core.deps import AgentDeps
from typing import Optional

class WebToolkit:
    """RISC Web Actions: 精简网页控制内核 (4 Atomic Instructions)."""

    @staticmethod
    def get_tools():
        return [
            WebToolkit.browser_navigate,
            WebToolkit.browser_get_distilled_dom,
            WebToolkit.browser_aria_snapshot,
            WebToolkit.browser_click,
            WebToolkit.browser_type,
            WebToolkit.browser_wait,
            WebToolkit.browser_screenshot,
        ]

    @staticmethod
    async def browser_navigate(ctx: RunContext[AgentDeps], url: str, headless: Optional[bool] = None) -> str:
        """Navigate to a website url (e.g. 'https://bing.com') using the stealth browser.
        Set headless=False if you encounter CAPTCHAs or want to show the browser to the user.
        """
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id, headless=headless)
        return await browser.navigate(url)

    @staticmethod
    async def browser_get_distilled_dom(ctx: RunContext[AgentDeps]) -> str:
        """Extract pure, hyper-clean text/markdown content from the current page. Best for reading articles."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.get_distilled_dom()

    @staticmethod
    async def browser_click(ctx: RunContext[AgentDeps], selector: str) -> str:
        """Click on an element using an ID from the latest browser_aria_snapshot (e.g. '12' or '[12]')."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.click(selector)

    @staticmethod
    async def browser_type(ctx: RunContext[AgentDeps], selector: str, text: str) -> str:
        """Type text into an input field using an ID from the latest browser_aria_snapshot (e.g. '12' or '[12]')."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.type(selector, text)

    # Note: Other tools like aria_snapshot, hover, scroll etc are internal/advanced
    # and can be added if needed, but the RISC goal is 4 core actions.

    @staticmethod
    async def browser_aria_snapshot(ctx: RunContext[AgentDeps]) -> str:
        """Get a high-density 'Accessibility Tree' snapshot. Lists UI elements by Role and Name."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.get_aria_snapshot()
        
    @staticmethod
    async def browser_wait(ctx: RunContext[AgentDeps], timeout_ms: int = 2000) -> str:
        """Wait for a certain amount of time before continuing."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.wait(timeout_ms)

    @staticmethod
    async def browser_screenshot(ctx: RunContext[AgentDeps], selector: Optional[str] = None) -> BinaryImage:
        """Take a screenshot of the page, or of a specific element identified by the latest browser_aria_snapshot."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        screenshot_dir = ctx.deps.kernel.get_session_workspace(ctx.deps.session_id) / "screenshots"
        return await browser.screenshot(selector, output_dir=screenshot_dir)
