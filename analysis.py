"""Reproduce the Seoul ASOS rain-positive-hour analysis and SVG figures.

Python 3.10+; standard library only. Run: python analysis.py
"""

from __future__ import annotations

import csv
import html
import json
import math
import statistics as stats
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/raw/seoul_asos_hourly_2024.csv"
FIGURES = ROOT / "images"
FIGURES.mkdir(exist_ok=True)


def median(values):
    return round(stats.median(values), 2) if values else None


def quartiles(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    return (
        min(ordered),
        stats.median(ordered[: n // 2]),
        stats.median(ordered),
        stats.median(ordered[(n + 1) // 2 :]),
        max(ordered),
    )


def fmt(value, places=1):
    return f"{value:.{places}f}"


def text(x, y, value, size=16, color="#1b2938", anchor="start", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{html.escape(str(value))}</text>')


def line(x1, y1, x2, y2, color="#cbd5df", width=1):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" />'


def svg_doc(width, height, elements):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">'
            '<rect width="100%" height="100%" fill="#ffffff" />'
            '<g font-family="Arial, sans-serif">' + "".join(elements) + '</g></svg>')


with SOURCE.open(encoding="cp949", newline="") as stream:
    source_rows = list(csv.DictReader(stream))

rows = []
for source in source_rows:
    when = datetime.strptime(source["일시"], "%Y-%m-%d %H:%M")
    temperature = float(source["기온(°C)"]) if source["기온(°C)"] else None
    rain_text = source["강수량(mm)"]
    rain = float(rain_text) if rain_text else None
    qc = source["강수량 QC플래그"]
    state = ("positive" if rain is not None and rain > 0 else
             "explicit_zero" if rain == 0 else
             "blank_qc9" if qc == "9" else "blank_no_flag")
    rows.append({"time": when, "temp": temperature, "rain": rain, "state": state})

assert len(rows) == 8784  # 366 days in leap year 2024
assert [r["time"] for r in rows] == [rows[0]["time"] + timedelta(hours=i) for i in range(len(rows))]
assert all(r["temp"] is not None for r in rows)
assert all(r["rain"] is None or r["rain"] >= 0 for r in rows)

state_counts = Counter(r["state"] for r in rows)
positives_year = [i for i, r in enumerate(rows) if r["state"] == "positive"]
# KMA supplies winter precipitation at 3-hour intervals. Keep intensity and
# lag comparisons in April-October, where the reporting interval is hourly.
CORE_MONTHS = tuple(range(4, 11))
positives = [i for i in positives_year if rows[i]["time"].month in CORE_MONTHS]

# Feasibility check for a common 3-hour rain interval. A warm-season window
# is usable under a conservative rule only if all three hourly amounts are
# numeric. Blank entries are deliberately not reclassified as zero.
three_hour_windows = Counter()
for i, row in enumerate(rows):
    if row["time"].month not in CORE_MONTHS or row["time"].hour % 3 or i < 2:
        continue
    block = rows[i - 2:i + 1]
    if any(item["time"].month not in CORE_MONTHS for item in block):
        continue
    three_hour_windows["total"] += 1
    if all(item["rain"] is not None for item in block):
        three_hour_windows["all_numeric"] += 1
    elif any(item["state"] == "blank_qc9" for item in block):
        three_hour_windows["has_qc9"] += 1
    else:
        three_hour_windows["blank_no_flag"] += 1

daily = defaultdict(list)
for row in rows:
    daily[row["time"].date()].append(row)

monthly_temp = {}
for month in range(1, 13):
    values = [r["temp"] for r in rows if r["time"].month == month]
    monthly_temp[str(month)] = round(stats.mean(values), 2)

hourly_daily_cycle = {
    str(hour): round(stats.mean(r["temp"] for r in rows if r["time"].hour == hour), 2)
    for hour in range(24)
}
rolling24 = [None] * len(rows)
for i in range(23, len(rows)):
    rolling24[i] = stats.mean(rows[j]["temp"] for j in range(i - 23, i + 1))


def bin_name(rain):
    if rain < 1:
        return "0.1-0.9"
    if rain < 5:
        return "1.0-4.9"
    return ">=5.0"


delta1_bins = defaultdict(list)
delta1_adjusted_bins = defaultdict(list)
delta24_months = defaultdict(list)
delta24_bins = defaultdict(list)
positive_days = set()
all_delta1_by_month_hour = defaultdict(list)
for i in range(1, len(rows)):
    key = (rows[i]["time"].month, rows[i]["time"].hour)
    all_delta1_by_month_hour[key].append(rows[i]["temp"] - rows[i - 1]["temp"])
baseline_delta1 = {key: stats.median(values) for key, values in all_delta1_by_month_hour.items()}
for i in positives:
    row = rows[i]
    positive_days.add(row["time"].date())
    if i >= 1:
        change1 = row["temp"] - rows[i - 1]["temp"]
        delta1_bins[bin_name(row["rain"])].append(change1)
        key = (row["time"].month, row["time"].hour)
        delta1_adjusted_bins[bin_name(row["rain"])].append(change1 - baseline_delta1[key])
    if i + 24 < len(rows):
        change = rows[i + 24]["temp"] - row["temp"]
        delta24_months[str(row["time"].month)].append(change)
        delta24_bins[bin_name(row["rain"])].append(change)

# Sensitivity view: only the last *positive measurement* of each calendar day.
# This is not the confirmed end of a rain event.
day_last_positive = {}
for i in positives:
    day_last_positive[rows[i]["time"].date()] = i
last_positive_changes = [
    rows[i + 24]["temp"] - rows[i]["temp"]
    for i in day_last_positive.values() if i + 24 < len(rows)
]


def summary(values):
    return {"n": len(values), "median": median(values),
            "mean": round(stats.mean(values), 2) if values else None,
            "negative_pct": round(100 * sum(v < 0 for v in values) / len(values), 1) if values else None}


metrics = {
    "source": "KMA ASOS, Seoul station 108, 2024-01-01 00:00 to 2024-12-31 23:00 KST",
    "rows": len(rows), "rain_state": dict(state_counts),
    "rain_positive_hours_year": len(positives_year),
    "core_months_for_hourly_rain_comparison": list(CORE_MONTHS),
    "rain_positive_hours_core": len(positives),
    "three_hour_warm_season_window_audit": dict(three_hour_windows),
    "rain_positive_days_year": len({rows[i]["time"].date() for i in positives_year}),
    "temperature_min_c": min(r["temp"] for r in rows),
    "temperature_max_c": max(r["temp"] for r in rows),
    "recorded_rain_max_mm": max(r["rain"] for r in rows if r["rain"] is not None),
    "recorded_rain_negative_count": sum(r["rain"] < 0 for r in rows if r["rain"] is not None),
    "rain_positive_days": len(positive_days),
    "monthly_mean_temperature_c": monthly_temp,
    "diurnal_mean_min_hour": min(hourly_daily_cycle, key=hourly_daily_cycle.get),
    "diurnal_mean_max_hour": max(hourly_daily_cycle, key=hourly_daily_cycle.get),
    "diurnal_mean_min_c": min(hourly_daily_cycle.values()),
    "diurnal_mean_max_c": max(hourly_daily_cycle.values()),
    "delta1_by_observed_rain_intensity": {key: summary(delta1_bins[key]) for key in ("0.1-0.9", "1.0-4.9", ">=5.0")},
    "delta1_adjusted_for_month_hour_by_intensity": {key: summary(delta1_adjusted_bins[key]) for key in ("0.1-0.9", "1.0-4.9", ">=5.0")},
    "delta24_by_month_at_positive_rain_hour": {str(m): summary(delta24_months[str(m)]) for m in CORE_MONTHS},
    "delta24_by_observed_rain_intensity": {key: summary(delta24_bins[key]) for key in ("0.1-0.9", "1.0-4.9", ">=5.0")},
    "delta24_at_last_positive_hour_per_day": summary(last_positive_changes),
    "delta24_all_positive_hours": summary([v for values in delta24_months.values() for v in values]),
}
(ROOT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


# Figure 1: complete hourly temperature series, 24h rolling mean, and known-positive rain marks.
W, H = 1200, 470
e = [text(70, 39, "Seoul hourly temperature and observed rainfall", 23, weight="bold"),
     text(70, 65, "Jan - Dec 2024 | winter rain is reported every 3 hours; ticks show measured values > 0 mm", 14, "#536576")]
left, right, top, bottom = 75, 1145, 105, 375
x = lambda i: left + (right - left) * i / (len(rows) - 1)
y = lambda t: bottom - (t + 20) * (bottom - top) / 60
for level in (-20, -10, 0, 10, 20, 30, 40):
    e += [line(left, y(level), right, y(level), "#e6ebf0"), text(62, y(level) + 5, level, 13, "#536576", "end")]
for month, label in ((1, "Jan"), (2, "Feb"), (3, "Mar"), (4, "Apr"), (5, "May"), (6, "Jun"), (7, "Jul"), (8, "Aug"), (9, "Sep"), (10, "Oct"), (11, "Nov"), (12, "Dec")):
    idx = next(i for i, r in enumerate(rows) if r["time"].month == month)
    e += [line(x(idx), top, x(idx), bottom, "#d3dce5"), text(x(idx) + 2, bottom + 23, label, 11, "#536576")]
for i in positives_year:
    e.append(line(x(i), bottom + 2, x(i), bottom + 18, "#1686ad", 1.5))
raw = " ".join(f"{fmt(x(i))},{fmt(y(r['temp']))}" for i, r in enumerate(rows))
ma = " ".join(f"{fmt(x(i))},{fmt(y(v))}" for i, v in enumerate(rolling24) if v is not None)
e += [f'<polyline points="{raw}" fill="none" stroke="#b4c2ce" stroke-width="1" opacity="0.75" />',
      f'<polyline points="{ma}" fill="none" stroke="#b8493c" stroke-width="2.5" />',
      line(left, bottom, right, bottom, "#344557"),
      text(left, 430, "Gray: hourly temperature", 14, "#536576"),
      text(335, 430, "Red: 24-hour moving average", 14, "#b8493c"),
      text(670, 430, "Blue ticks: recorded rainfall > 0 mm", 14, "#1686ad"),
      text(25, 235, "°C", 15, "#536576")]
(FIGURES / "01_temperature_timeline.svg").write_text(svg_doc(W, H, e), encoding="utf-8")


def boxplot_figure(title, subtitle, datasets, labels, filename, y_min, y_max):
    width, height = 900, 480
    items = [text(70, 42, title, 23, weight="bold"), text(70, 68, subtitle, 14, "#536576")]
    xl, xr, yt, yb = 95, 850, 108, 390
    yy = lambda v: yb - (v - y_min) * (yb - yt) / (y_max - y_min)
    step = 5 if y_max - y_min <= 30 else 10
    first = math.ceil(y_min / step) * step
    for tick in range(first, int(y_max) + 1, step):
        items += [line(xl, yy(tick), xr, yy(tick), "#e6ebf0"), text(xl - 13, yy(tick) + 4, tick, 13, "#536576", "end")]
    if y_min < 0 < y_max:
        items.append(line(xl, yy(0), xr, yy(0), "#748598", 1.5))
    for n, (label, values) in enumerate(zip(labels, datasets)):
        center = xl + (n + 0.5) * (xr - xl) / len(labels)
        q = quartiles(values)
        if not q:
            continue
        low, q1, med, q3, high = q
        low, high = max(low, y_min), min(high, y_max)
        items += [line(center, yy(low), center, yy(high), "#2b657f", 2),
                  line(center - 16, yy(low), center + 16, yy(low), "#2b657f", 2),
                  line(center - 16, yy(high), center + 16, yy(high), "#2b657f", 2),
                  f'<rect x="{center - 35}" y="{yy(q3)}" width="70" height="{max(1, yy(q1) - yy(q3))}" '
                  'fill="#c9e8f1" stroke="#2b657f" stroke-width="2" />',
                  line(center - 35, yy(med), center + 35, yy(med), "#b8493c", 3),
                  text(center, 420, label, 15, anchor="middle", weight="bold"),
                  text(center, 442, f"n={len(values)}", 13, "#536576", "middle")]
    items += [text(42, 99, "°C", 14, "#536576"),
              text(850, 99, "Whiskers clipped to chart range; box = Q1-Q3, red = median", 12, "#536576", "end")]
    (FIGURES / filename).write_text(svg_doc(width, height, items), encoding="utf-8")


boxplot_figure(
    "Hourly temperature change relative to typical month-hour",
    "Apr-Oct positive-rain hours; 1h change minus median for the same month and clock hour",
    [delta1_adjusted_bins[key] for key in ("0.1-0.9", "1.0-4.9", ">=5.0")],
    ["0.1-0.9 mm", "1.0-4.9 mm", ">=5.0 mm"],
    "02_rain_intensity_delta1_adjusted.svg", -12, 12,
)
boxplot_figure(
    "Temperature 24 hours after a recorded rain hour",
    "Apr-Oct: T(t+24h) - T(t); overlapping rain hours are not independent episodes",
    [delta24_months[str(m)] for m in CORE_MONTHS],
    ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"],
    "03_delta24_by_month.svg", -15, 15,
)
print(json.dumps(metrics, ensure_ascii=True, indent=2))
