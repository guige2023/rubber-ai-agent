#!/usr/bin/env python3
import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

SUBMIT_PATTERNS = [
    r"submit\s+your\s+tool",
    r"submit\s+tool",
    r"submit\s+site",
    r"add\s+your\s+tool",
    r"add\s+tool",
    r"list\s+your\s+tool",
    r"list\s+tool",
    r"get\s+listed",
    r"suggest\s+a\s+tool",
    r"submit\s+website",
    r"submit\s+product",
    r"add\s+listing",
    r"submit\s+listing",
]

RAW_HTML_PATTERNS = [
    r'href=["\'][^"\']*/submit[^"\']*["\']',
    r'href=["\'][^"\']*/submit-tool[^"\']*["\']',
    r'href=["\'][^"\']*/submit-your-tool[^"\']*["\']',
    r'href=["\'][^"\']*/add-tool[^"\']*["\']',
    r'href=["\'][^"\']*/get-listed[^"\']*["\']',
    r'>\s*submit\s*<',
    r'>\s*add\s+tool\s*<',
    r'>\s*submit\s+tool\s*<',
]

ANCHOR_HREF_PATTERNS = [
    r'<a\b[^>]*href=["\']([^"\']*/submit[^"\']*)["\'][^>]*>(.*?)</a>',
    r'<a\b[^>]*href=["\']([^"\']*/submit-tool[^"\']*)["\'][^>]*>(.*?)</a>',
    r'<a\b[^>]*href=["\']([^"\']*/submit-your-tool[^"\']*)["\'][^>]*>(.*?)</a>',
    r'<a\b[^>]*href=["\']([^"\']*/add-tool[^"\']*)["\'][^>]*>(.*?)</a>',
    r'<a\b[^>]*href=["\']([^"\']*/get-listed[^"\']*)["\'][^>]*>(.*?)</a>',
]

GENERIC_CTA_ELEMENT_PATTERNS = [
    r'<a\b([^>]*)>(.*?)</a>',
    r'<button\b([^>]*)>(.*?)</button>',
]

SOFT_BLOCK_PATTERNS = [
    r"checking\s+your\s+browser",
    r"verify\s+you\s+are\s+human",
    r"attention\s+required",
    r"captcha",
    r"cf-chl-",
    r"cloudflare",
]

JS_APP_MARKERS = [
    "__NEXT_DATA__",
    "id=\"__next\"",
    "id='__next'",
    "id=\"root\"",
    "id='root'",
    "id=\"app\"",
    "id='app'",
    "data-reactroot",
    "window.__NUXT__",
    "id=\"__nuxt\"",
    "id='__nuxt'",
    "ng-version",
    "id=\"svelte\"",
    "id='svelte'",
]


@dataclass
class VerificationResult:
    url: str
    accessible: bool
    submit_signal_found: bool
    submit_signal_snippet: Optional[str]
    failure_reason: Optional[str]
    final_url: Optional[str]
    verification_method: str
    browser_fallback_recommended: bool = False
    browser_fallback_reason: Optional[str] = None


def _normalize_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_submit_signal(text: str) -> Optional[str]:
    lowered = text.lower()
    for pattern in SUBMIT_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            start = max(match.start() - 40, 0)
            end = min(match.end() + 40, len(text))
            return text[start:end].strip()
    return None


def _extract_submit_signal_from_html(html: str) -> Optional[str]:
    for pattern in GENERIC_CTA_ELEMENT_PATTERNS:
        for match in re.finditer(pattern, html, re.I | re.S):
            attrs = match.group(1)
            inner_html = match.group(2)
            text = _normalize_text(inner_html)
            lowered = text.lower()
            if not text:
                continue
            if any(
                marker in lowered
                for marker in (
                    "submit your tool",
                    "submit tool",
                    "submit site",
                    "submit product",
                    "add your tool",
                    "add tool",
                    "get listed",
                    "list your tool",
                    "suggest a tool",
                    "submit ai tool",
                    "submit",
                )
            ):
                href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, re.I)
                if href_match:
                    return f"{text} ({href_match.group(1)})"
                return text

    for pattern in ANCHOR_HREF_PATTERNS:
        match = re.search(pattern, html, re.I | re.S)
        if match:
            href = match.group(1)
            anchor_html = match.group(2)
            anchor_text = _normalize_text(anchor_html)
            if anchor_text:
                return f"{anchor_text} ({href})"
            return href

    for pattern in RAW_HTML_PATTERNS:
        match = re.search(pattern, html, re.I)
        if match:
            start = max(match.start() - 120, 0)
            end = min(match.end() + 220, len(html))
            fragment = html[start:end]
            normalized = _normalize_text(fragment)
            if normalized:
                return normalized
            return re.sub(r"\s+", " ", fragment).strip()
    return None


def _detect_submit_signal(html: str) -> Optional[str]:
    text = _normalize_text(html)
    return _extract_submit_signal_from_html(html) or _extract_submit_signal(text)


def _looks_like_soft_block(html: str, text: str) -> bool:
    haystacks = (html.lower(), text.lower())
    return any(re.search(pattern, haystack) for haystack in haystacks for pattern in SOFT_BLOCK_PATTERNS)


def _looks_like_js_app_shell(html: str, text: str) -> bool:
    html_lower = html.lower()
    text_word_count = len(text.split())
    script_count = len(re.findall(r"(?is)<script\b", html))
    marker_found = any(marker.lower() in html_lower for marker in JS_APP_MARKERS)
    tiny_body = text_word_count < 120
    javascript_prompt = "enable javascript" in text.lower() or "requires javascript" in text.lower()
    return (marker_found and tiny_body) or (script_count >= 8 and tiny_body) or javascript_prompt


def _browser_fallback_reason(html: str, submit_signal_found: bool) -> Optional[str]:
    if submit_signal_found:
        return None

    text = _normalize_text(html)
    if _looks_like_soft_block(html, text):
        return "anti_bot_or_human_verification_page"
    if _looks_like_js_app_shell(html, text):
        return "client_side_rendering_suspected"
    return None


def verify_url(url: str, timeout: float = 10.0) -> VerificationResult:
    if not urlparse(url).scheme:
        url = f"https://{url}"

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            raw = response.read(1024 * 1024)
            try:
                html = raw.decode("utf-8")
            except UnicodeDecodeError:
                html = raw.decode("latin-1", errors="replace")
            snippet = _detect_submit_signal(html)
            fallback_reason = _browser_fallback_reason(html, snippet is not None)
            result = VerificationResult(
                url=url,
                accessible=True,
                submit_signal_found=snippet is not None,
                submit_signal_snippet=snippet,
                failure_reason=None,
                final_url=final_url,
                verification_method="http",
                browser_fallback_recommended=fallback_reason is not None,
                browser_fallback_reason=fallback_reason,
            )
            return result
    except HTTPError as exc:
        status_reason = f"HTTP {exc.code}"
        return VerificationResult(
            url=url,
            accessible=False,
            submit_signal_found=False,
            submit_signal_snippet=None,
            failure_reason=status_reason,
            final_url=None,
            verification_method="http",
            browser_fallback_recommended=exc.code in {401, 403, 429},
            browser_fallback_reason=status_reason if exc.code in {401, 403, 429} else None,
        )
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        reason_text = f"network error: {reason}"
        return VerificationResult(
            url=url,
            accessible=False,
            submit_signal_found=False,
            submit_signal_snippet=None,
            failure_reason=reason_text,
            final_url=None,
            verification_method="http",
            browser_fallback_recommended=True,
            browser_fallback_reason=reason_text,
        )
    except Exception as exc:
        reason_text = str(exc)
        return VerificationResult(
            url=url,
            accessible=False,
            submit_signal_found=False,
            submit_signal_snippet=None,
            failure_reason=reason_text,
            final_url=None,
            verification_method="http",
            browser_fallback_recommended=any(
                marker in reason_text.lower()
                for marker in ("timeout", "ssl", "certificate", "network error")
            ),
            browser_fallback_reason=reason_text
            if any(marker in reason_text.lower() for marker in ("timeout", "ssl", "certificate", "network error"))
            else None,
        )


def main(argv: List[str]) -> int:
    if not argv:
        print(json.dumps({"error": "No URLs provided"}, ensure_ascii=False))
        return 1

    results = [asdict(verify_url(url)) for url in argv]
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
