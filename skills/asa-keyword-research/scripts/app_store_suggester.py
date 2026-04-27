import json
import logging
import plistlib
import argparse
import sys
import requests
from typing import List

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class SuggestionLookupError(RuntimeError):
    """Raised when App Store suggestions cannot be retrieved reliably."""


class AppStoreSuggester:
    def __init__(self) -> None:
        self.url = "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        # 国家与 Storefront ID 的映射。X-Apple-Store-Front 格式为
        # `${storefront_id}-${language_variation_id},${platform_id}`。
        self.countries = {
            "CN": "143465", "US": "143441", "GB": "143444", "CA": "143455", "AU": "143460",
            "DE": "143443", "FR": "143442", "IT": "143450", "ES": "143454",
            "JP": "143462", "HK": "143463", "TW": "143470", "NZ": "143461",
            "KR": "143466",
            "SE": "143456", "CH": "143459", "BR": "143503", "MX": "143468",
            "ID": "143476", "MY": "143473", "PH": "143474", "TH": "143475",
            "VN": "143471", "RU": "143469", "UA": "143492", "TR": "143480",
            "SA": "143479", "EG": "143516"
        }

    def get_suggestions(self, term: str, country_code: str = "US") -> List[str]:
        country_code = country_code.upper()
        if country_code not in self.countries:
            supported = ", ".join(sorted(self.countries))
            raise SuggestionLookupError(f"未知国家代码: {country_code}. 支持: {supported}")

        store_front_id = self.countries[country_code]
        store_front_header = f"{store_front_id}-1,29"

        current_headers = self.headers.copy()
        current_headers["X-Apple-Store-Front"] = store_front_header

        params = {
            "clientApplication": "Software",
            "term": term
        }

        try:
            response = requests.get(self.url, headers=current_headers, params=params, timeout=10)
            response.raise_for_status()
            plist_data = plistlib.loads(response.content)
        except requests.RequestException as exc:
            raise SuggestionLookupError(f"请求 Apple Search Hints 失败: {exc}") from exc
        except plistlib.InvalidFileException as exc:
            raise SuggestionLookupError("Apple Search Hints 返回了无法解析的 plist 数据") from exc

        hints = plist_data.get("hints")
        if not isinstance(hints, list):
            raise SuggestionLookupError("Apple Search Hints 响应缺少 hints 列表")

        suggestions: list[str] = []
        for item in hints:
            if isinstance(item, dict) and isinstance(item.get("term"), str):
                suggestions.append(item["term"])
        return suggestions

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="获取 App Store 搜索建议")
    parser.add_argument("--term", required=True, help="搜索关键词")
    parser.add_argument("--country", default="US", help="国家代码 (如 CN, US, JP)")
    
    args = parser.parse_args()
    
    suggester = AppStoreSuggester()
    try:
        results = suggester.get_suggestions(args.term, args.country)
    except SuggestionLookupError as exc:
        logger.error(str(exc))
        print(
            json.dumps(
                {"ok": False, "error": {"type": exc.__class__.__name__, "message": str(exc)}},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    print(json.dumps(results, ensure_ascii=False))
