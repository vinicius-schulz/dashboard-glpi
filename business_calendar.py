"""Business calendar helpers.

Provides:
- load_holidays(path) -> set of dates
- is_business_day(dt) -> bool
- previous_business_day(dt) -> pd.Timestamp (previous business day < dt)
- business_days_range_start(dt) -> previous business day (inclusive)
- business_days_between(start, end) -> number of business days (float, counts partial days not handled here)

Holidays are loaded from `holidays.json` file at repo root (ISO dates).
"""
from __future__ import annotations

from typing import Set
import json
import os
import pandas as pd

HOLIDAYS_PATH = os.path.join(os.path.dirname(__file__), 'holidays.json')

def load_holidays(path: str = HOLIDAYS_PATH) -> Set[pd.Timestamp]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        dates = set()
        for k in raw.keys():
            try:
                dates.add(pd.Timestamp(k).normalize())
            except Exception:
                continue
        return dates
    except Exception:
        return set()

_holidays = load_holidays()

def is_business_day(dt: pd.Timestamp) -> bool:
    if dt is None or pd.isna(dt):
        return False
    d = pd.Timestamp(dt).normalize()
    # weekday: Monday=0 ... Sunday=6
    if d.dayofweek >= 5:
        return False
    if d in _holidays:
        return False
    return True

def previous_business_day(dt: pd.Timestamp) -> pd.Timestamp:
    """Return the most recent business day strictly before `dt`.

    If `dt` itself is business day, returns the previous business day (not dt).
    """
    cur = pd.Timestamp(dt).normalize() - pd.Timedelta(days=1)
    guard = 0
    while guard < 365:
        if is_business_day(cur):
            return cur
        cur -= pd.Timedelta(days=1)
        guard += 1
    # fallback: return dt-1
    return pd.Timestamp(dt).normalize() - pd.Timedelta(days=1)

def business_days_between(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Count business days between start (inclusive) and end (exclusive).

    Both are normalized to dates. Returns int count.
    """
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    if e <= s:
        return 0
    cur = s
    cnt = 0
    while cur < e:
        if is_business_day(cur):
            cnt += 1
        cur += pd.Timedelta(days=1)
    return cnt


def consecutive_non_business_start(dt: pd.Timestamp) -> pd.Timestamp:
    """Return the start date of the consecutive non-business-day block that ends at `dt`.

    If `dt` is a business day, returns dt.normalize().
    If dt and the days immediately before it are non-business (weekend/holiday),
    returns the earliest date in that consecutive non-business run.
    """
    cur = pd.Timestamp(dt).normalize()
    # If today is business day, nothing to include
    if is_business_day(cur):
        return cur
    # Walk backwards until we hit a business day (exclusive)
    guard = 0
    while guard < 365:
        prev = cur - pd.Timedelta(days=1)
        if is_business_day(prev):
            # previous day is business -> current cur is start of non-business block
            return cur
        cur = prev
        guard += 1
    return cur
