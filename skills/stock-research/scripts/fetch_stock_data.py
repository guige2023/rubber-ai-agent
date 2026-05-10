#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class StockDataError(RuntimeError):
    """Raised when yfinance cannot return usable stock data."""


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def numeric_value(value: Any, default: float | int | None = 0) -> float | int | None:
    value = json_safe(value)
    return value if isinstance(value, int | float) else default


def dataframe_row_value(frame: pd.DataFrame, label: str, column: Any, default: float | int | None = 0) -> float | int | None:
    if label not in frame.index or column not in frame.columns:
        return default
    return numeric_value(frame.loc[label, column], default)


def price_history_rows(history: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if history.empty:
        return rows

    for index, row in history.iterrows():
        close = json_safe(row.get("Close"))
        if close is None:
            continue
        rows.append(
            {
                "date": json_safe(index),
                "open": json_safe(row.get("Open")),
                "high": json_safe(row.get("High")),
                "low": json_safe(row.get("Low")),
                "close": close,
                "volume": json_safe(row.get("Volume")) or 0,
            }
        )
    return rows


def get_5y_financials(stock: yf.Ticker) -> list[dict[str, Any]]:
    """Fetch and process up to 5 years of annual financial statements."""
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance = stock.balance_sheet
    except Exception as exc:
        raise StockDataError(f"Financial statements fetch failed: {exc}") from exc

    if financials.empty and cashflow.empty and balance.empty:
        return []

    years = list(dict.fromkeys([*financials.columns, *cashflow.columns, *balance.columns]))[:5]
    data: list[dict[str, Any]] = []
    for year in years:
        revenue = dataframe_row_value(financials, "Total Revenue", year, default=None)
        net_income = dataframe_row_value(financials, "Net Income", year, default=None)
        equity = dataframe_row_value(balance, "Stockholders Equity", year, default=None)
        operating_cash_flow = dataframe_row_value(cashflow, "Operating Cash Flow", year, default=None)
        capital_expenditure = dataframe_row_value(cashflow, "Capital Expenditure", year, default=None)
        if all(value is None for value in (revenue, net_income, equity, operating_cash_flow)):
            continue

        net_income_value = numeric_value(net_income, 0) or 0
        equity_value = numeric_value(equity, 0) or 0
        operating_cash_flow_value = numeric_value(operating_cash_flow, 0) or 0
        capital_expenditure_value = numeric_value(capital_expenditure, 0) or 0
        data.append(
            {
                "Year": year.strftime("%Y") if hasattr(year, "strftime") else str(year),
                "Revenue": numeric_value(revenue, 0),
                "Net Income": net_income_value,
                "Operating Cash Flow": operating_cash_flow_value,
                "Free Cash Flow": operating_cash_flow_value + capital_expenditure_value,
                "ROE": net_income_value / equity_value if equity_value else 0,
                "EPS": dataframe_row_value(financials, "Diluted EPS", year, default=None),
            }
        )
    return data


def fetch_stock_data(ticker: str) -> dict[str, Any]:
    stock = yf.Ticker(ticker)
    history = stock.history(period="1y")
    if history.empty:
        raise StockDataError(f"Ticker {ticker} not found or returned no price history.")

    info = stock.info
    if not isinstance(info, dict):
        info = {}

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "currency": info.get("currency", "USD"),
        "exchange": info.get("exchange"),
        "ttm_metrics": {
            "price": info.get("currentPrice", history["Close"].iloc[-1]),
            "pe": info.get("trailingPE"),
            "pb": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "fcf": info.get("freeCashflow"),
            "eps": info.get("trailingEps"),
            "revenue_growth": info.get("revenueGrowth"),
        },
        "historical_financials": get_5y_financials(stock),
        "price_history": price_history_rows(history),
        "chart_path": None,
        "data_note": "Chart image generation is disabled in the bundled runtime.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Fetching data for %s...", ticker)
    try:
        result = fetch_stock_data(ticker)
    except StockDataError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
