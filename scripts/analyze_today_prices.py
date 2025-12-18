"""Analyze today's Nordpool prices with central heating logic.

Purpose:
- Fetch today's quarter-hour prices (96 values) from Home Assistant PRICE_SENSOR
- Run should_central_heating_run() against each quarter's price
- Print contiguous BLOCKED intervals (meaning should_run == False)

This helps verify:
- 15-minute granularity works end-to-end
- No time shifting: index 0 is 00:00 local, index 36 is 09:00 local etc.

Usage (recommended):
  uv run python scripts/analyze_today_prices.py

Optional:
  START_HOUR=8 END_HOUR=10 uv run python scripts/analyze_today_prices.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Tuple

import requests
from dotenv import load_dotenv

from main import (
    HA_URL,
    PRICE_SENSOR,
    headers,
    MAX_SHUTOFF_HOURS,
    PRICE_ALWAYS_ON_THRESHOLD,
    should_central_heating_run,
)


def _hour_min_from_index(i: int) -> Tuple[int, int]:
    hour = i // 4
    minute = (i % 4) * 15
    return hour, minute


def _fmt_hm(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}"


def fetch_today_prices() -> List[float]:
    resp = requests.get(f"{HA_URL}/api/states/{PRICE_SENSOR}", headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    prices = data.get("attributes", {}).get("today", [])
    if len(prices) != 96:
        raise RuntimeError(f"Expected 96 quarter-hour prices, got {len(prices)}")
    return [float(p) for p in prices]


@dataclass
class Interval:
    start_index: int
    end_index_exclusive: int

    @property
    def start_hm(self) -> str:
        h, m = _hour_min_from_index(self.start_index)
        return _fmt_hm(h, m)

    @property
    def end_hm(self) -> str:
        # end is exclusive; show the real end time
        h, m = _hour_min_from_index(self.end_index_exclusive)
        return _fmt_hm(h, m)


def find_blocked_intervals(prices: List[float]) -> List[Interval]:
    blocked = []
    start = None

    for i, p in enumerate(prices):
        should_run, _reason = should_central_heating_run(p, prices)
        is_blocked = not should_run

        if is_blocked and start is None:
            start = i
        elif not is_blocked and start is not None:
            blocked.append(Interval(start, i))
            start = None

    if start is not None:
        blocked.append(Interval(start, 96))

    return blocked


def main() -> None:
    load_dotenv()

    start_hour = int(os.getenv("START_HOUR", "0"))
    end_hour = int(os.getenv("END_HOUR", "24"))

    prices = fetch_today_prices()

    print("Central heating decision analysis (today)")
    print(f"HA_URL: {HA_URL}")
    print(f"PRICE_SENSOR: {PRICE_SENSOR}")
    print(f"Always-on threshold: {PRICE_ALWAYS_ON_THRESHOLD} c/kWh")
    print(f"Max shutoff hours: {MAX_SHUTOFF_HOURS} (=> {int(MAX_SHUTOFF_HOURS*4)} quarters)")

    print("\nPrices and decisions:")
    print("time   price  should_run")
    print("-----  -----  ----------")

    start_index = max(0, start_hour * 4)
    end_index = min(96, end_hour * 4)

    for i in range(start_index, end_index):
        h, m = _hour_min_from_index(i)
        p = prices[i]
        should_run, reason = should_central_heating_run(p, prices)
        print(f"{_fmt_hm(h,m)}  {p:5.2f}  {str(should_run):>10}  # {reason}")

    blocked = find_blocked_intervals(prices)
    print("\nBlocked intervals (heating OFF / switch ON):")
    if not blocked:
        print("  (none)")
    else:
        for itv in blocked:
            print(f"  {itv.start_hm} - {itv.end_hm}")


if __name__ == "__main__":
    main()
