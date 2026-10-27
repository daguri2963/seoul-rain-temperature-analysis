"""Read KMA weather-phenomenon time notation and audit against daily duration.

KMA ground-observation guide 10.5.1: phenomenon+time starts/observes it;
an unlabelled time ends it. A leading/trailing '-' carries across midnight.
Run: python -X utf8 scripts/parse_rain_articles.py
"""

import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRECIP = {'비', '이슬비', '소나기', '눈', '진눈깨비', '싸락눈', '가루눈',
          '어는비', '싸락우박', '우박', '눈보라', '소낙눈'}
TIME = re.compile(r'(?<![\d{])(?:[01]\d|2[0-3])[0-5]\d(?![\d}])|(?<!\d)2400(?!\d)')
TAG = re.compile(r'\{([^{}]+)\}')


def parse_article(day, article, carry_in=()):
    midnight = datetime.combine(day, datetime.min.time())
    spans = []
    for clause in re.split(r'\s+|(?<=\.)(?=-?\{)', article.strip()):
        kinds = [tag for tag in TAG.findall(clause) if tag in PRECIP]
        if not kinds:
            continue
        matches = list(TIME.finditer(clause))
        if not matches:
            raise ValueError(f'Precipitation clause without time: {day} {clause}')
        first_tags = TAG.findall(clause[:matches[0].start()])
        # July 19 omits the leading carry mark. Only infer midnight carry
        # when the previous day's record explicitly continues the same kind
        # and the first marker is an intensity observation, not a start.
        continuation = (kinds[0] in carry_in and
                        any(re.fullmatch('강도[012]', tag) for tag in first_tags))
        kind = kinds[0] if clause.startswith('-') or continuation else None
        active_start = 0 if kind else None
        levels = []
        previous = 0
        for match in matches:
            marker = clause[previous:match.start()]
            tags = TAG.findall(marker)
            marker_kinds = [tag for tag in tags if tag in PRECIP]
            clock = match.group()
            minute = int(clock[:2]) * 60 + int(clock[2:])
            if marker_kinds and marker.rstrip().endswith('}'):
                new_kind = marker_kinds[-1]
                if kind is not None and new_kind != kind:
                    spans.append((active_start, minute, kind, tuple(levels)))
                    active_start, levels = minute, []
                if kind is None:
                    active_start, levels = minute, []
                kind = new_kind
                levels += [int(tag[-1]) for tag in tags if re.fullmatch('강도[012]', tag)]
            elif tags and all(re.fullmatch('강도[012]', tag) for tag in tags) and kind:
                levels += [int(tag[-1]) for tag in tags]
            else:
                if kind is None:
                    raise ValueError(f'End without active precipitation: {day} {clause}')
                spans.append((active_start, minute, kind, tuple(levels)))
                active_start, kind, levels = None, None, []
            previous = match.end()
        if kind is not None:
            if not clause.rstrip('.').endswith('-') and matches[-1].group() != '2400':
                raise ValueError(f'Unterminated precipitation clause: {day} {clause}')
            spans.append((active_start, 1440, kind, tuple(levels)))
    result = []
    for start, end, kind, levels in spans:
        if end < start:
            raise ValueError(f'Reversed interval: {day} {start} {end}')
        if end > start:
            result.append({'start': midnight + timedelta(minutes=start),
                           'end': midnight + timedelta(minutes=end),
                           'kind': kind, 'levels': levels})
    return result


def union_minutes(spans):
    merged = []
    for span in sorted(spans, key=lambda x: x['start']):
        if merged and span['start'] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span['end'])
        else:
            merged.append([span['start'], span['end']])
    return sum((end - start).total_seconds() / 60 for start, end in merged)


def load_and_audit():
    with (ROOT / 'data/raw/seoul_asos_daily_2024.csv').open(encoding='cp949', newline='') as stream:
        daily = list(csv.DictReader(stream))
    assert len(daily) == 366
    assert [row['일시'] for row in daily] == [(datetime(2024, 1, 1) + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(366)]
    intervals, differences, errors = [], [], []
    carry_in = set()
    for row in daily:
        day = datetime.strptime(row['일시'], '%Y-%m-%d').date()
        try:
            spans = parse_article(day, row['기사'], carry_in)
            next_midnight = datetime.combine(day + timedelta(days=1), datetime.min.time())
            carry_in = {s['kind'] for s in spans if s['end'] == next_midnight}
            intervals.extend(spans)
            observed_hours = float(row['강수 계속시간(hr)']) if row['강수 계속시간(hr)'] else 0
            assert not row['일강수량(mm)'] or float(row['일강수량(mm)']) == 0 or observed_hours > 0
            parsed_hours = union_minutes(spans) / 60
            if abs(parsed_hours - observed_hours) > .011:
                differences.append({'date': day.isoformat(), 'official_hours': observed_hours,
                                    'parsed_hours': round(parsed_hours, 4), 'article': row['기사']})
        except ValueError as error:
            errors.append(str(error))
    return daily, intervals, differences, errors


if __name__ == '__main__':
    daily, intervals, differences, errors = load_and_audit()
    destination = ROOT / 'data/processed'
    destination.mkdir(exist_ok=True)
    audit = {'days': len(daily), 'interval_segments': len(intervals),
             'daily_duration_mismatches': differences, 'parse_errors': errors}
    (destination / 'rain_article_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(audit, ensure_ascii=False, indent=2))
