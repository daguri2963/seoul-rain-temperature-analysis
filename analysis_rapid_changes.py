"""Look retrospectively for rainfall-pattern signs around >=5 C changes.

Run after analysis_patterns.py: python -X utf8 analysis_rapid_changes.py
Uses official daily means and the unchanged original rainfall classification.
Outcome-selected subsets are NOT an estimate of independent forecast skill.
"""

import csv
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'analysis_config.json').read_text(encoding='utf-8'))
THRESHOLD = Decimal(str(CONFIG['rapid_change_threshold_c']))
GROUPS = ('short_shower', 'light_persistent')
OUT = ROOT / 'data/processed'

with (ROOT / 'data/raw/seoul_asos_daily_2024.csv').open(encoding='cp949', newline='') as stream:
    daily = list(csv.DictReader(stream))
means = {date.fromisoformat(r['일시']): Decimal(r['평균기온(°C)']) for r in daily}
days = sorted(means)
assert len(days) == len(daily) == 366
assert days == [date(2024, 1, 1) + timedelta(days=i) for i in range(366)]

with (OUT / 'rain_episodes_2024.csv').open(encoding='utf-8-sig', newline='') as stream:
    episodes = list(csv.DictReader(stream))
for episode in episodes:
    episode['_start'] = datetime.fromisoformat(episode['start'])
    episode['_end'] = datetime.fromisoformat(episode['end'])
core = [e for e in episodes if e['group'] in GROUPS]
assert len(core) == 25


def shoulder_block(day):
    return 'spring' if day.month in (3, 4, 5) else 'autumn' if day.month in (9, 10, 11) else None


def within_shoulder(first, last):
    return bool(shoulder_block(first) and shoulder_block(first) == shoulder_block(last)
                and (last - first).days < 93)


def numeric(value):
    return round(float(value), 3)


def write_csv(name, records):
    keys = list(dict.fromkeys(key for row in records for key in row))
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(records)


calendar_windows, calendar_metrics = [], {}
for lag in CONFIG['rapid_calendar_lags_days']:
    eligible = []
    for target in days:
        baseline = target - timedelta(days=lag)
        if baseline not in means:
            continue
        change = means[target] - means[baseline]
        shoulder = within_shoulder(baseline, target)
        eligible.append((target, shoulder))
        if abs(change) < THRESHOLD:
            continue
        direction = 'up' if change > 0 else 'down'
        # The baseline day's mean is already complete. Only use a fully
        # observed pattern after it and before the target day begins.
        between_start = datetime.combine(baseline + timedelta(days=1), datetime.min.time())
        target_start = datetime.combine(target, datetime.min.time())
        complete_core = [e for e in core if e['_start'] >= between_start and e['_end'] <= target_start]
        matching = [e['id'] for e in complete_core if (e['group'] == 'short_shower') == (direction == 'down')]
        opposing = [e['id'] for e in complete_core if e['id'] not in matching]
        context = [e for e in episodes if e['_start'] < target_start and e['_end'] > between_start]
        state = ('both' if matching and opposing else 'matching_only' if matching else
                 'opposing_only' if opposing else 'no_core_sign')
        calendar_windows.append({
            'lag_days': lag, 'baseline_day': baseline.isoformat(), 'target_day': target.isoformat(),
            'baseline_daily_mean_c': numeric(means[baseline]), 'target_daily_mean_c': numeric(means[target]),
            'change_c': numeric(change), 'direction': direction, 'shoulder_eligible': shoulder,
            'matching_core_ids': '|'.join(matching), 'opposing_core_ids': '|'.join(opposing), 'sign_state': state,
            'all_precipitation_context_ids': '|'.join(e['id'] for e in context),
            'context_groups': '|'.join(sorted({e['group'] for e in context})),
        })
    calendar_metrics[str(lag)] = {}
    for subset in ('all_year', 'spring_autumn'):
        chosen = [r for r in calendar_windows if r['lag_days'] == lag and
                  (subset == 'all_year' or r['shoulder_eligible'])]
        calendar_metrics[str(lag)][subset] = {
            'eligible_comparisons': sum(subset == 'all_year' or flag for _, flag in eligible),
            'rapid_windows': len(chosen), 'warming_windows': sum(r['direction'] == 'up' for r in chosen),
            'cooling_windows': sum(r['direction'] == 'down' for r in chosen),
            'sign_state_counts': dict(Counter(r['sign_state'] for r in chosen)),
            'unique_matching_episode_ids': sorted({x for r in chosen for x in r['matching_core_ids'].split('|') if x}),
            'unique_opposing_episode_ids': sorted({x for r in chosen for x in r['opposing_core_ids'].split('|') if x}),
        }
write_csv('rapid_calendar_windows_2024.csv', calendar_windows)

comparisons = []
for e in core:
    start_day, end_day = e['_start'].date(), (e['_end'] - timedelta(microseconds=1)).date()
    for length in (1, *CONFIG['rapid_pre_post_average_lengths_days']):
        before = [start_day - timedelta(days=i) for i in range(length, 0, -1)]
        after = [end_day + timedelta(days=i) for i in range(1, length + 1)]
        if not all(day in means for day in before + after):
            continue
        before_sum, after_sum = sum(means[d] for d in before), sum(means[d] for d in after)
        difference_sum = after_sum - before_sum
        change = difference_sum / length
        expected = 'down' if e['group'] == 'short_shower' else 'up'
        direction = 'up' if change > 0 else 'down' if change < 0 else 'flat'
        rapid = abs(difference_sum) >= THRESHOLD * length
        span = (after[-1] - before[0]).days
        comparisons.append({
            'id': e['id'], 'group': e['group'], 'start': e['start'], 'end': e['end'],
            'average_length_days': length, 'before_first': before[0].isoformat(), 'before_last': before[-1].isoformat(),
            'after_first': after[0].isoformat(), 'after_last': after[-1].isoformat(),
            'calendar_span_days': span, 'before_mean_c': numeric(before_sum / length),
            'after_mean_c': numeric(after_sum / length), 'change_c': numeric(change),
            'direction': direction, 'rapid_ge_5c': rapid, 'expected_direction': expected,
            'agrees_with_hypothesis': direction == expected,
            'shoulder_eligible': within_shoulder(before[0], after[-1]),
            'primary_2_or_3_day_gap': length == 1 and span in CONFIG['rapid_calendar_lags_days'],
            'another_precipitation_on_first_target_day': e['another_precipitation_on_target_day'],
        })
write_csv('rapid_episode_comparisons_2024.csv', comparisons)


def summarize(records):
    answer = {}
    for subset in ('all_year', 'spring_autumn'):
        answer[subset] = {}
        for group in GROUPS:
            chosen = [r for r in records if r['group'] == group and (subset == 'all_year' or r['shoulder_eligible'])]
            rapid = [r for r in chosen if r['rapid_ge_5c']]
            agreeing = [r for r in rapid if r['agrees_with_hypothesis']]
            answer[subset][group] = {
                'eligible_episodes': len(chosen), 'rapid_episodes': len(rapid),
                'agreeing_rapid_episodes': len(agreeing), 'opposing_rapid_episodes': len(rapid) - len(agreeing),
                'rapid_episode_ids': [r['id'] for r in rapid], 'agreeing_episode_ids': [r['id'] for r in agreeing],
            }
    return answer


primary = [r for r in comparisons if r['primary_2_or_3_day_gap']]
primary_metrics = summarize(primary)
block_metrics = {str(length): summarize([r for r in comparisons if r['average_length_days'] == length])
                 for length in CONFIG['rapid_pre_post_average_lengths_days']}
rapid_primary = [r for r in primary if r['rapid_ge_5c']]
rapid_targets = {r['target_day'] for r in calendar_windows}
metrics = {
    'daily_source_rows': len(daily), 'threshold_c_inclusive': numeric(THRESHOLD),
    'calendar_lag_definition': 'daily_mean(target) - daily_mean(target-lag), not a moving-average difference',
    'calendar_window_counts': calendar_metrics,
    'calendar_union_unique_target_dates': len(rapid_targets),
    'calendar_union_matching_episode_ids': sorted({x for r in calendar_windows for x in r['matching_core_ids'].split('|') if x}),
    'calendar_union_opposing_episode_ids': sorted({x for r in calendar_windows for x in r['opposing_core_ids'].split('|') if x}),
    'original_episode_aligned_2_or_3_day_changes': primary_metrics,
    'pre_post_multiday_average_sensitivity': block_metrics,
    'primary_rapid_cases': rapid_primary,
    'interpretation': 'Retrospective search conditioned on a large observed outcome; not a causal test or forecast accuracy.'
}
(ROOT / 'rapid_change_metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(metrics, ensure_ascii=False, indent=2))


def figures():
    cache = ROOT / '.cache/matplotlib'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR', str(cache))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib import font_manager
    font = Path('C:/Windows/Fonts/malgun.ttf')
    if font.exists():
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams['axes.unicode_minus'] = False
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, sharey=True)
    for ax, lag in zip(axes, CONFIG['rapid_calendar_lags_days']):
        ax.plot(days, [float(means[d]) for d in days], color='#89949e', linewidth=1)
        for direction, color, marker, label in [('up', '#c66536', '^', '5°C 이상 상승'),
                                                 ('down', '#297aaf', 'v', '5°C 이상 하강')]:
            rows = [r for r in calendar_windows if r['lag_days'] == lag and r['direction'] == direction]
            dates = [date.fromisoformat(r['target_day']) for r in rows]
            ax.scatter(dates, [float(means[d]) for d in dates], color=color, marker=marker, s=36,
                       label=f'{label}: {len(rows)}비교쌍', zorder=3)
        ax.set_title(f'일평균기온을 {lag}일 전과 비교한 급변 도착일', fontsize=12)
        ax.set_ylabel('공식 일평균기온 (°C)')
        ax.legend(loc='upper right', fontsize=9, ncol=2)
        ax.grid(alpha=.2)
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m월'))
    fig.suptitle('서울 2024년: 2~3일 간격으로 일평균기온이 5°C 이상 변한 구간', fontsize=15)
    fig.text(.5, .025, '색 점은 비교 도착일이며 서로 독립적인 전선·강수 사건 수를 뜻하지 않음', ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .05, 1, .95))
    fig.savefig(ROOT / 'images/08_rapid_daily_mean_changes.png', dpi=180)
    plt.close(fig)

    names = {'short_shower': '짧은 소나기', 'light_persistent': '약한 지속성 강수'}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True)
    for ax, group, color in zip(axes, GROUPS, ['#287fa6', '#b96732']):
        sets = [[r['change_c'] for r in comparisons if r['group'] == group and r['average_length_days'] == length]
                for length in (1, 2, 3)]
        boxes = ax.boxplot(sets, tick_labels=[f'전후 {k}일 평균\n(n={len(v)})' for k, v in zip((1, 2, 3), sets)],
                           patch_artist=True, showfliers=False)
        for box in boxes['boxes']:
            box.set_facecolor(color)
            box.set_alpha(.25)
        for pos, values in enumerate(sets, 1):
            ax.scatter([pos + (i % 5 - 2) * .04 for i in range(len(values))], values, color=color, s=25, alpha=.8)
        ax.axhline(0, color='#536676', linewidth=.8)
        ax.axhline(float(THRESHOLD), color='#b7483b', linestyle='--', linewidth=1)
        ax.axhline(-float(THRESHOLD), color='#b7483b', linestyle='--', linewidth=1)
        ax.axhspan(-float(THRESHOLD), float(THRESHOLD), color='#8c9ba6', alpha=.08)
        ax.set_title(names[group])
        ax.grid(axis='y', alpha=.2)
    axes[0].set_ylabel('강수 후 평균 - 강수 전 평균 (°C)')
    fig.suptitle('강수 전후 평균 구간 길이를 바꿨을 때의 기온 변화', fontsize=15)
    fig.text(.5, .02, '전체 핵심 사례를 표시 · 붉은 점선: ±5°C · 2·3일 평균끼리의 비교는 2·3일 전과의 비교와 다름',
             ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .06, 1, .93))
    fig.savefig(ROOT / 'images/09_rapid_pattern_average_windows.png', dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    figures()
