"""Evaluate recorded rainfall patterns against next-day temperature features.

Run build_daily_temperature.py first, then python -X utf8 analysis_patterns.py.
Pattern labels use official weather articles only, never later temperature.
"""

import csv
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median

from scripts.parse_rain_articles import load_and_audit

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'analysis_config.json').read_text(encoding='utf-8'))
OUT = ROOT / 'data/processed'
METRICS = ('dawn_mean_c', 'daily_max_official_c', 'evening_mean_c')
GROUPS = ('short_shower', 'light_persistent')
daily, spans, mismatches, errors = load_and_audit()
assert not errors and not mismatches, 'Article parsing must match independent daily duration'


def merged_intervals(parts):
    merged = []
    for part in sorted(parts, key=lambda x: x['start']):
        if merged and part['start'] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], part['end'])
        else:
            merged.append([part['start'], part['end']])
    return merged


def season(day):
    if day.month in (3, 4, 5):
        return 'spring'
    if day.month in (9, 10, 11):
        return 'autumn'
    return 'summer' if day.month in (6, 7, 8) else 'winter'


episodes = []
gap = timedelta(hours=CONFIG['episode_dry_gap_hours'])
for span in sorted(spans, key=lambda x: x['start']):
    if not episodes or span['start'] - episodes[-1]['end'] >= gap:
        episodes.append({'start': span['start'], 'end': span['end'], 'parts': [span]})
    else:
        episodes[-1]['parts'].append(span)
        episodes[-1]['end'] = max(episodes[-1]['end'], span['end'])

# Freeze labels before loading any temperature outcomes.
for number, episode in enumerate(episodes, 1):
    merged = merged_intervals(episode['parts'])
    episode['id'] = f'E{number:03}'
    episode['kinds'] = sorted({p['kind'] for p in episode['parts']})
    levels = [level for p in episode['parts'] for level in p['levels']]
    episode['max_observed_intensity_code'] = max(levels) if levels else None
    episode['elapsed_h'] = (episode['end'] - episode['start']).total_seconds() / 3600
    episode['wet_h'] = sum((end - start).total_seconds() / 3600 for start, end in merged)
    episode['longest_continuous_h'] = max((end - start).total_seconds() / 3600 for start, end in merged)
    kinds = set(episode['kinds'])
    if not kinds <= {'비', '이슬비', '소나기'}:
        group = 'snow_or_mixed'
    elif kinds == {'소나기'} and episode['elapsed_h'] <= CONFIG['short_shower_max_elapsed_hours']:
        group = 'short_shower'
    elif (kinds <= {'비', '이슬비'} and
          episode['longest_continuous_h'] >= CONFIG['steady_min_continuous_hours'] and
          levels and max(levels) <= CONFIG['steady_max_observed_intensity_code']):
        group = 'light_persistent'
    else:
        group = 'other_rain'
    episode['group'] = group

print(json.dumps({'episode_count': len(episodes), 'labels_before_outcomes': dict(Counter(e['group'] for e in episodes))},
                 ensure_ascii=False))

with (OUT / 'temperature_daily_2024.csv').open(encoding='utf-8-sig', newline='') as stream:
    temperature_rows = list(csv.DictReader(stream))
temperatures = {date.fromisoformat(r['date']): {m: float(r[m]) for m in METRICS} for r in temperature_rows}
neutral = CONFIG['temperature_neutral_band_c']


def direction(value):
    return 'down' if value < -neutral else 'up' if value > neutral else 'flat'


def baseline_probability(episode, metric, expected, shoulder_only=False):
    # Retrospective calendar comparison, NOT a trained operational forecast.
    # Match starting month and number of calendar days between endpoints.
    start = episode['start'].date()
    target_offset = (episode['target_day'] - start).days
    signs = []
    for anchor in temperatures:
        before, after = anchor - timedelta(days=1), anchor + timedelta(days=target_offset)
        if (anchor.month == start.month and anchor != start and before in temperatures and after in temperatures
                and (not shoulder_only or season(before) == season(after) == season(start))):
            signs.append(direction(temperatures[after][metric] - temperatures[before][metric]))
    return sum(sign == expected for sign in signs) / len(signs) if signs else None


for episode in episodes:
    start_day = episode['start'].date()
    # A 00:00 endpoint belongs to the preceding precipitation day.
    end_day = (episode['end'] - timedelta(microseconds=1)).date()
    episode['baseline_day'] = start_day - timedelta(days=1)
    episode['target_day'] = end_day + timedelta(days=1)
    episode['shoulder_eligible'] = (
        season(episode['baseline_day']) in ('spring', 'autumn') and
        season(episode['baseline_day']) == season(episode['target_day']) and
        (episode['target_day'] - episode['baseline_day']).days < 93)
    episode['temperature_eligible'] = episode['baseline_day'] in temperatures and episode['target_day'] in temperatures
    episode['another_precipitation_on_target_day'] = any(
        other is not episode and other['start'].date() <= episode['target_day'] <= (other['end'] - timedelta(microseconds=1)).date()
        for other in episodes)
    if episode['temperature_eligible']:
        for metric in METRICS:
            change = temperatures[episode['target_day']][metric] - temperatures[episode['baseline_day']][metric]
            episode[metric + '_change'] = round(change, 3)
            episode[metric + '_direction'] = direction(change)


def summarize(selected, metric, expected, shoulder_only=False):
    values = [e[metric + '_change'] for e in selected]
    signs = Counter(e[metric + '_direction'] for e in selected)
    bases = [baseline_probability(e, metric, expected, shoulder_only) for e in selected]
    return {
        'n': len(values), 'median_change_c': round(median(values), 2) if values else None,
        'mean_change_c': round(mean(values), 2) if values else None,
        'down_n': signs['down'], 'flat_n': signs['flat'], 'up_n': signs['up'],
        'expected_direction': expected, 'agreement_n': signs[expected],
        'agreement_pct': round(100 * signs[expected] / len(values), 1) if values else None,
        'strict_sign_agreement_n': sum(v < 0 if expected == 'down' else v > 0 for v in values),
        'calendar_reference_expected_pct': round(100 * mean(b for b in bases if b is not None), 1) if values else None,
        'target_days_with_other_precip_n': sum(e['another_precipitation_on_target_day'] for e in selected),
    }


results = {}
for subset in ('all_year', 'spring_autumn'):
    results[subset] = {}
    for group in GROUPS:
        selected = [e for e in episodes if e['group'] == group and e['temperature_eligible']
                    and (subset == 'all_year' or e['shoulder_eligible'])]
        expected = 'down' if group == 'short_shower' else 'up'
        results[subset][group] = {metric: summarize(selected, metric, expected, subset == 'spring_autumn') for metric in METRICS}

no_additional_rain = {}
for subset in ('all_year', 'spring_autumn'):
    no_additional_rain[subset] = {}
    for group in GROUPS:
        selected = [e for e in episodes if e['group'] == group and e['temperature_eligible']
                    and not e['another_precipitation_on_target_day']
                    and (subset == 'all_year' or e['shoulder_eligible'])]
        expected = 'down' if group == 'short_shower' else 'up'
        no_additional_rain[subset][group] = {m: summarize(selected, m, expected, subset == 'spring_autumn') for m in METRICS}

serializable = []
for episode in episodes:
    record = {key: value for key, value in episode.items() if key != 'parts'}
    for key, value in list(record.items()):
        if isinstance(value, (date, datetime)):
            record[key] = value.isoformat()
        elif isinstance(value, list):
            record[key] = '|'.join(value)
    serializable.append(record)
fieldnames = list(dict.fromkeys(key for record in serializable for key in record))
with (OUT / 'rain_episodes_2024.csv').open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(serializable)

with (OUT / 'precipitation_intervals_2024.csv').open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['start', 'end', 'phenomenon', 'observed_intensity_codes'])
    for span in sorted(spans, key=lambda x: x['start']):
        writer.writerow([span['start'].isoformat(), span['end'].isoformat(), span['kind'],
                         '|'.join(map(str, span['levels']))])

audit = {
    'raw_daily_rows': len(daily), 'article_duration_mismatch_days': len(mismatches),
    'parsed_interval_segments': len(spans), 'all_precipitation_episodes': len(episodes),
    'episode_group_counts': dict(Counter(e['group'] for e in episodes)),
    'boundary_temperature_exclusions': sum(not e['temperature_eligible'] for e in episodes),
    'results': results,
    'sensitivity_excluding_other_precipitation_on_target_day': no_additional_rain,
    'start_month_by_group': {g: dict(Counter(str(e['start'].month) for e in episodes if e['group'] == g)) for g in GROUPS},
    'interpretation': 'Exploratory fixed-hypothesis agreement; no front identification or independent forecast validation.'
}
(ROOT / 'pattern_metrics.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(audit, ensure_ascii=False, indent=2))


def create_figures():
    cache = ROOT / '.cache/matplotlib'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR', str(cache))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    windows_font = Path('C:/Windows/Fonts/malgun.ttf')
    if windows_font.exists():
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(windows_font)).get_name()
    plt.rcParams['axes.unicode_minus'] = False
    labels = {'dawn_mean_c': '새벽 평균 (04~06시)', 'daily_max_official_c': '공식 일최고기온',
              'evening_mean_c': '저녁 평균 (18~21시)'}
    names = {'short_shower': '짧은 소나기', 'light_persistent': '약한 지속성 강수'}
    colors = ['#287fa6', '#b96732']
    fig, axes = plt.subplots(2, 3, figsize=(12, 8), sharey=True)
    for row, subset in enumerate(('all_year', 'spring_autumn')):
        for col, metric in enumerate(METRICS):
            ax = axes[row, col]
            sets = [[e[metric + '_change'] for e in episodes if e['group'] == group and e['temperature_eligible']
                     and (subset == 'all_year' or e['shoulder_eligible'])] for group in GROUPS]
            drawn = ax.boxplot(sets, tick_labels=[names[g] + f'\n(n={len(v)})' for g, v in zip(GROUPS, sets)],
                               patch_artist=True, showmeans=True, showfliers=False)
            for box, color in zip(drawn['boxes'], colors):
                box.set_facecolor(color)
                box.set_alpha(.35)
            for position, values in enumerate(sets, 1):
                ax.scatter([position + ((i % 5) - 2) * .035 for i in range(len(values))], values,
                           s=16, color=colors[position - 1], alpha=.7, zorder=3)
            ax.axhline(0, color='#526575', linewidth=1)
            ax.axhspan(-neutral, neutral, color='#9ba9b6', alpha=.14)
            ax.set_title(('연중 전체' if subset == 'all_year' else '봄·가을만') + ' / ' + labels[metric], fontsize=11)
            ax.grid(axis='y', alpha=.2)
            if col == 0:
                ax.set_ylabel('종료 다음날 - 시작 전날 (°C)')
    fig.suptitle('강수 양상별 이후 기온 변화: 연중 전체와 봄·가을 비교', fontsize=16)
    fig.text(.5, .025, '회색 띠: ±0.5°C 보합 · 점: 강수 사례 · 상자: 사분위 범위 · 선: 중앙값 · 삼각형: 평균', ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .055, 1, .95))
    fig.savefig(ROOT / 'images/05_pattern_temperature_seasons.png', dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.5), sharey=True)
    for ax, metric in zip(axes, METRICS):
        positions = [0, 1, 3, 4]
        for position, (subset, group) in zip(positions, [(s, g) for s in ('all_year', 'spring_autumn') for g in GROUPS]):
            result = results[subset][group][metric]
            color = colors[GROUPS.index(group)]
            if result['n']:
                ax.bar(position, result['agreement_pct'], color=color, width=.7, alpha=.8)
                ax.text(position, result['agreement_pct'] + 2,
                        f"{result['agreement_n']}/{result['n']}", ha='center', fontsize=10)
                ax.scatter(position, result['calendar_reference_expected_pct'], color='#172c3b', marker='_', s=300,
                           linewidths=2, zorder=4)
        ax.set_xticks([.5, 3.5], ['연중 전체', '봄·가을'])
        ax.set_ylim(0, 115)
        ax.set_title(labels[metric], fontsize=11)
        ax.grid(axis='y', alpha=.2)
    axes[0].set_ylabel('가설 방향 일치율 (%)')
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    fig.legend(handles=[Patch(color=colors[0], label='소나기 → 하강'), Patch(color=colors[1], label='약한 지속성 → 상승'),
                        Line2D([0], [0], color='#172c3b', marker='_', linestyle='', markersize=15,
                               label='같은 월·경과일의 달력 기준 빈도')], loc='lower center', ncol=3, fontsize=9)
    fig.suptitle('강수 양상 가설은 얼마나 일치했나? (±0.5°C 보합 포함)', fontsize=15)
    fig.tight_layout(rect=(0, .1, 1, .92))
    fig.savefig(ROOT / 'images/06_pattern_agreement.png', dpi=180)
    plt.close(fig)

    # Choose examples solely by closeness to each group's median duration.
    # Temperature outcomes do not participate in selecting examples.
    with (ROOT / 'data/raw/seoul_asos_hourly_2024.csv').open(encoding='cp949', newline='') as stream:
        hourly = [(datetime.strptime(r['일시'], '%Y-%m-%d %H:%M'), float(r['기온(°C)']))
                  for r in csv.DictReader(stream)]
    fig, axes = plt.subplots(2, 1, figsize=(12, 6.5))
    import matplotlib.dates as mdates
    for ax, group, color in zip(axes, GROUPS, colors):
        candidates = [e for e in episodes if e['group'] == group and e['temperature_eligible']]
        middle = median(e['elapsed_h'] for e in candidates)
        example = min(candidates, key=lambda e: abs(e['elapsed_h'] - middle))
        frame_start = datetime.combine(example['baseline_day'], datetime.min.time())
        frame_end = datetime.combine(example['target_day'] + timedelta(days=1), datetime.min.time())
        series = [(t, value) for t, value in hourly if frame_start <= t < frame_end]
        ax.plot([v[0] for v in series], [v[1] for v in series], color='#364e60', linewidth=1.5)
        for part in example['parts']:
            ax.axvspan(part['start'], part['end'], color=color, alpha=.25)
        ax.set_title(f"{names[group]} / {example['id']} / {example['start']:%m-%d %H:%M} ~ "
                     f"{example['end']:%m-%d %H:%M} / 지속 {example['elapsed_h']:.2f}시간", fontsize=11)
        ax.set_ylabel('시간별 기온 (°C)')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M'))
        ax.grid(alpha=.2)
    fig.suptitle('관측 기사로 확인한 강수 양상 사례와 전후 기온', fontsize=15)
    fig.text(.5, .02, '색 띠: 실제 강수 현상 기록 구간 · 대표 사례는 기온이 아닌 지속시간 중앙값으로 선택', ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .05, 1, .94))
    fig.savefig(ROOT / 'images/07_recorded_pattern_examples.png', dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    create_figures()
