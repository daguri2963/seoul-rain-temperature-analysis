"""Verify submission artifacts against original observations using Decimal.

Run after the documented analysis commands: python -X utf8 scripts/verify_submission.py
Checks source-derived temperature values, direction boundaries, summary counts,
calendar references and local Markdown/image links. Does not infer causality.
"""

import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from importlib.metadata import version
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
checks = []


def check(name, passed, detail=None):
    item = {'name': name, 'passed': bool(passed)}
    if detail is not None:
        item['detail'] = detail
    checks.append(item)


def read_csv(relative, encoding):
    with (ROOT / relative).open(encoding=encoding, newline='') as stream:
        return list(csv.DictReader(stream))


def quantize(value):
    return value.quantize(Decimal('0.001'), rounding=ROUND_HALF_EVEN)


def expected_direction(value):
    return 'down' if value < Decimal('-.5') else 'up' if value > Decimal('.5') else 'flat'


hourly = read_csv('data/raw/seoul_asos_hourly_2024.csv', 'cp949')
daily = read_csv('data/raw/seoul_asos_daily_2024.csv', 'cp949')
features = read_csv('data/processed/temperature_daily_2024.csv', 'utf-8-sig')
episodes = read_csv('data/processed/rain_episodes_2024.csv', 'utf-8-sig')
metrics = json.loads((ROOT / 'pattern_metrics.json').read_text(encoding='utf-8'))
report = (ROOT / 'REPORT.md').read_text(encoding='utf-8')
times = [datetime.strptime(row['일시'], '%Y-%m-%d %H:%M') for row in hourly]
check('hourly_source_8784_continuous_points', len(times) == 8784 and
      times == [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(8784)])
check('one_station_108', all(row['지점'] == '108' for row in hourly + daily))
check('daily_source_366_unique_days', len(daily) == len({row['일시'] for row in daily}) == 366)
check('temperature_no_missing', all(row['기온(°C)'] for row in hourly) and all(row['최고기온(°C)'] for row in daily))

source_hours = defaultdict(dict)
for when, row in zip(times, hourly):
    source_hours[when.date()][when.hour] = Decimal(row['기온(°C)'])
official_max = {date.fromisoformat(row['일시']): Decimal(row['최고기온(°C)']) for row in daily}
source_features = {}
for day, hours in source_hours.items():
    source_features[day] = {
        'dawn_mean_c': quantize(sum(hours[h] for h in (4, 5, 6)) / 3),
        'daily_max_official_c': official_max[day],
        'evening_mean_c': quantize(sum(hours[h] for h in (18, 19, 20, 21)) / 4),
    }
columns = tuple(next(iter(source_features.values())))
feature_errors = [(row['date'], metric) for row in features for metric in columns
                  if Decimal(row[metric]) != source_features[date.fromisoformat(row['date'])][metric]]
check('daily_features_independently_recomputed_from_sources', len(features) == 366 and not feature_errors, feature_errors)

episode_errors = []
for row in episodes:
    if row['temperature_eligible'] != 'True':
        continue
    before, after = date.fromisoformat(row['baseline_day']), date.fromisoformat(row['target_day'])
    for metric in columns:
        difference = quantize(source_features[after][metric] - source_features[before][metric])
        if (difference != Decimal(row[metric + '_change']) or
                expected_direction(difference) != row[metric + '_direction']):
            episode_errors.append([row['id'], metric])
check('episode_changes_and_directions_from_decimal_sources', not episode_errors, episode_errors)
regression = next(row for row in episodes if row['id'] == 'E063')
check('exact_minus_point_five_is_neutral', regression['daily_max_official_c_change'] == '-0.5'
      and regression['daily_max_official_c_direction'] == 'flat')

summary_errors, calendar_errors, report_errors = [], [], []
for subset in ('all_year', 'spring_autumn'):
    for group in ('short_shower', 'light_persistent'):
        selected = [row for row in episodes if row['group'] == group and row['temperature_eligible'] == 'True'
                    and (subset == 'all_year' or row['shoulder_eligible'] == 'True')]
        expected = 'down' if group == 'short_shower' else 'up'
        for metric in columns:
            result = metrics['results'][subset][group][metric]
            values = [Decimal(row[metric + '_change']) for row in selected]
            hits = sum(expected_direction(v) == expected for v in values)
            if result['n'] != len(selected) or result['agreement_n'] != hits or abs(float(median(values)) - result['median_change_c']) > .011:
                summary_errors.append([subset, group, metric])
            if f"{hits}/{len(selected)} ({100 * hits / len(selected):.1f}%)" not in report:
                report_errors.append([subset, group, metric])
            reference_frequencies = []
            for row in selected:
                start = datetime.fromisoformat(row['start']).date()
                offset = (date.fromisoformat(row['target_day']) - start).days
                signs = []
                for anchor in source_features:
                    before, after = anchor - timedelta(days=1), anchor + timedelta(days=offset)
                    same_season = ((before.month in (3, 4, 5) and after.month in (3, 4, 5) and start.month in (3, 4, 5)) or
                                   (before.month in (9, 10, 11) and after.month in (9, 10, 11) and start.month in (9, 10, 11)))
                    if (anchor.month == start.month and anchor != start and before in source_features and after in source_features
                            and (subset == 'all_year' or same_season)):
                        signs.append(expected_direction(quantize(source_features[after][metric] - source_features[before][metric])))
                reference_frequencies.append(Decimal(sum(sign == expected for sign in signs)) / len(signs))
            independent_reference = round(float(sum(reference_frequencies) / len(reference_frequencies) * 100), 1)
            if independent_reference != result['calendar_reference_expected_pct']:
                calendar_errors.append([subset, group, metric, independent_reference])
check('primary_summary_counts_and_medians', not summary_errors, summary_errors)
check('calendar_references_recomputed_with_decimal', not calendar_errors, calendar_errors)
check('all_12_report_agreement_cells_match_results', not report_errors, report_errors)

article_audit = json.loads((ROOT / 'data/processed/rain_article_audit.json').read_text(encoding='utf-8'))
check('article_duration_check_366_days', article_audit['days'] == 366 and
      not article_audit['daily_duration_mismatches'] and not article_audit['parse_errors'])

broken_links = []
for path in ROOT.rglob('*.md'):
    if '.cache' in path.parts:
        continue
    for target in re.findall(r'\]\((?!https?://)([^)]+)\)', path.read_text(encoding='utf-8')):
        relative = target.split('#', 1)[0]
        # This check's own JSON is written at the end of the current run.
        target_path = (path.parent / relative).resolve()
        if relative and target_path != ROOT / 'submission_checks.json' and not target_path.exists():
            broken_links.append([str(path.relative_to(ROOT)), target])
check('all_local_markdown_links_exist', not broken_links, broken_links)
images = re.findall(r'!\[[^]]*\]\(([^)]+)\)', report)
image_errors = []
for relative in images:
    path = ROOT / relative
    if path.suffix == '.svg':
        ET.parse(path)
    elif path.suffix == '.png' and path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
        image_errors.append(relative)
check('report_has_4_readable_image_files', len(images) == 4 and not image_errors, images)
check('report_has_ai_log_and_required_sections', all(title in report for title in
      ('## 1.', '## 2.', '## 3.', '## 5.', '## 6.', '## 7.', '## 8. AI 사용', '## 9.')))
check('python_supported', sys.version_info >= (3, 10))

record = {'review_date': '2026-10-27', 'python_version': sys.version.split()[0],
          'matplotlib_version': version('matplotlib'), 'all_passed': all(item['passed'] for item in checks),
          'checks': checks, 'limits': 'Artifact and calculation verification only; not proof of causality, forecast skill or learner understanding.'}
(ROOT / 'submission_checks.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False, indent=2))
sys.exit(0 if record['all_passed'] else 1)
