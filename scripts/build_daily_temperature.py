"""Prepare dawn/evening means and official daily maxima for rain-pattern analysis.

Run: python scripts/build_daily_temperature.py
The official maximum stays blank until data/raw/seoul_asos_daily_2024.csv exists.
"""

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
config = json.loads((ROOT / 'analysis_config.json').read_text(encoding='utf-8'))
source = ROOT / 'data/raw/seoul_asos_hourly_2024.csv'
official_source = ROOT / 'data/raw/seoul_asos_daily_2024.csv'
destination = ROOT / 'data/processed'
destination.mkdir(exist_ok=True)

with source.open(encoding='cp949', newline='') as stream:
    hourly = list(csv.DictReader(stream))
days = defaultdict(dict)
for row in hourly:
    when = datetime.strptime(row['일시'], '%Y-%m-%d %H:%M')
    assert when.hour not in days[when.date()], 'Duplicate hourly temperature'
    days[when.date()][when.hour] = float(row['기온(°C)'])

official = {}
if official_source.exists():
    # KMA downloaded CSV uses CP949; keep original bytes unchanged.
    with official_source.open(encoding='cp949', newline='') as stream:
        official_rows = list(csv.DictReader(stream))
    assert official_rows and '최고기온(°C)' in official_rows[0]
    for row in official_rows:
        day = datetime.strptime(row['일시'], '%Y-%m-%d').date()
        assert day not in official, 'Duplicate official daily maximum'
        official[day] = float(row['최고기온(°C)']) if row['최고기온(°C)'] else None

records = []
for day, hours in sorted(days.items()):
    assert set(hours) == set(range(24)), f'Incomplete day: {day}'
    dawn = list(range(config['dawn_hours_inclusive'][0], config['dawn_hours_inclusive'][1] + 1))
    evening = list(range(config['evening_hours_inclusive'][0], config['evening_hours_inclusive'][1] + 1))
    season = ('spring' if day.month in (3, 4, 5) else 'summer' if day.month in (6, 7, 8)
              else 'autumn' if day.month in (9, 10, 11) else 'winter')
    records.append({
        'date': day.isoformat(), 'season': season,
        'in_shoulder_months': int(day.month in config['shoulder_months']),
        'dawn_mean_c': round(mean(hours[h] for h in dawn), 3),
        'dawn_hour_count': len(dawn),
        'daily_max_official_c': official.get(day, ''),
        'hourly_sample_max_c': max(hours.values()),
        'evening_mean_c': round(mean(hours[h] for h in evening), 3),
        'evening_hour_count': len(evening),
    })

expected_first = datetime(config['year'], 1, 1).date()
assert [r['date'] for r in records] == [(expected_first + timedelta(days=i)).isoformat() for i in range(366)]
assert len(records) == 366
if official:
    assert all(official.get(day) is None or official[day] >= max(hours.values()) - 0.11
               for day, hours in days.items()), 'Official maximum is unexpectedly below hourly maximum'

with (destination / 'temperature_daily_2024.csv').open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)

audit = {
    'days': len(records),
    'shoulder_days': sum(r['in_shoulder_months'] for r in records),
    'dawn_hours': dawn, 'evening_hours': evening,
    'official_daily_source_present': official_source.exists(),
    'official_daily_max_values': sum(isinstance(r['daily_max_official_c'], (int, float)) for r in records),
    'stage': 'temperature_feature_preparation',
    'note': 'Temperature features only; no rain blanks were imputed or rain events inferred.'
}
(destination / 'temperature_features_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(audit, ensure_ascii=True, indent=2))
