"""Audit the original KMA ASOS CSV without imputing precipitation blanks.

Run from the project root: python scripts/audit_asos.py
"""

import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/seoul_asos_hourly_2024.csv"
SUMMER_SOURCE = ROOT / "data/raw/seoul_asos_hourly_2024-06_09.csv"


with SOURCE.open(encoding="cp949", newline="") as stream:
    reader = csv.reader(stream)
    header = next(reader)
    rows = list(reader)

times = [datetime.strptime(row[2], "%Y-%m-%d %H:%M") for row in rows]
expected = [times[0] + timedelta(hours=hour) for hour in range(len(times))]
rain_state = Counter()
positive_indices = []

for index, row in enumerate(rows):
    rain, flag = row[5], row[6]
    if rain:
        if float(rain) > 0:
            rain_state["positive"] += 1
            positive_indices.append(index)
        else:
            rain_state["explicit_zero"] += 1
    elif flag == "9":
        rain_state["blank_qc9"] += 1
    else:
        rain_state["blank_no_flag"] += 1

with SUMMER_SOURCE.open(encoding="cp949", newline="") as stream:
    summer_rows = list(csv.reader(stream))[1:]
annual_summer_rows = [row for row in rows if "2024-06-01" <= row[2][:10] <= "2024-09-30"]

result = {
    "source": str(SOURCE),
    "columns": header,
    "rows": len(rows),
    "first": times[0].isoformat(timespec="minutes"),
    "last": times[-1].isoformat(timespec="minutes"),
    "hourly_grid_complete": times == expected,
    "temperature_blank": sum(not row[3] for row in rows),
    "rain_state": dict(rain_state),
    "rain_positive_days": len({times[i].date() for i in positive_indices}),
    "rain_positive_hours_apr_oct": sum(times[i].month in range(4, 11) for i in positive_indices),
    "summer_subset_matches_original": annual_summer_rows == summer_rows,
}
print(json.dumps(result, ensure_ascii=True, indent=2))
