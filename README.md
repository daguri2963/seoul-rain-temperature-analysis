# 강수 양상과 다음날 기온: 서울 2024년

최종 결과는 [REPORT.md](REPORT.md)에 있다. 기상청 서울(108)의 시간자료 **8,784개**와 추가 일자료 **366일**을 사용한다. 가설은 **짧은 소나기 뒤 하강 / 약하고 지속적인 강수 뒤 상승**이다. 새벽·공식 일최고·저녁 기온을 연중 전체와 봄·가을 범위로 비교했다.

강수량 공란을 임의로 0으로 채우지 않고, 일기현상 기사의 시·분 기록으로 양상을 추출했다. 기사에서 계산한 하루 강수 시간을 공식 강수 계속시간과 366일 모두 대조했다. 사후 사례 일치율이며 운영 가능한 예보 정확도를 검증한 것은 아니다.

## 실행

Python 3.10 이상이 필요하다. 작성 환경은 Python 3.14.7, Matplotlib 3.10.8이다.

```powershell
python -m pip install -r requirements.txt
python analysis.py
python scripts/build_daily_temperature.py
python -X utf8 scripts/parse_rain_articles.py
python -X utf8 analysis_patterns.py
```

- `analysis.py`: 초기 시간자료 지표와 SVG 그림 3개를 생성한다.
- `build_daily_temperature.py`: 새벽 04~06시 평균·공식 일최고·저녁 18~21시 평균을 366일 표로 만든다.
- `parse_rain_articles.py`: 기상청 기사 시각을 읽고 공식 강수 계속시간과 대조한다.
- `analysis_patterns.py`: 양상을 분류한 뒤 기온을 연결하고 결과 JSON·사례 CSV·PNG 그림 3개를 생성한다. 기사 검증이 실패하면 중단한다.

설정은 [analysis_config.json](analysis_config.json)에 있다. Matplotlib는 Windows의 맑은 고딕이 있으면 사용하고, 다른 환경에서는 한글 글꼴을 별도로 설정해야 한다. 원본 CSV는 CP949, 가공 CSV는 UTF-8 BOM이다.

## 주요 파일

```text
analysis_patterns.py              # 현재 핵심 분석
analysis_config.json              # 시간대·계절·분류 기준
analysis.py                       # 초기 탐색, 연간 기온 그림
REPORT.md                         # 최종 리포트
PRD.md                            # 최종 기준과 작업 체크리스트
requirements.txt
data/raw/
  seoul_asos_hourly_2024.csv
  seoul_asos_daily_2024.csv
  seoul_asos_hourly_2024-06_09.csv  # 초기 범위 대조용
data/processed/
  temperature_daily_2024.csv
  temperature_features_audit.json
  precipitation_intervals_2024.csv
  rain_episodes_2024.csv
  rain_article_audit.json
pattern_metrics.json              # 핵심 결과와 재강수 제외 민감도
metrics.json                      # 초기 시간자료 탐색 지표
images/                           # SVG·PNG 시각화
scripts/                          # 기사 파싱·기온 집계·원본 점검
docs/EARLIER_EXPLORATION.md        # 초기 탐색 기록
```

## 원본 다시 받기

[기상청 ASOS 자료](https://data.kma.go.kr/data/grnd/selectAsosRltmList.do?pgmNo=36)에 로그인하고 지점 **서울(108)**, 기간 **2024-01-01~2024-12-31**로 지정한다.

1. **시간자료:** 시작 00시·종료 23시, 기온·기온 QC·강수량·강수량 QC. `seoul_asos_hourly_2024.csv`로 보존한다.
2. **일자료:** 기온 전체, 강수 전체, 눈 전체, 일기현상 중 **기사**를 선택한다. 공식 최고기온·강수 계속시간·소나기/비의 시각 기사가 핵심이다. `seoul_asos_daily_2024.csv`로 보존한다.
3. 다운로드 사용분야는 교육/행정으로 선택했다. 원본은 수정하지 않고 `data/raw/`에 둔다.

선택 화면에 시간별 현상번호·운형도 있지만 이번 핵심 분석에는 추가 수집하지 않았다. 최종 가설 분류는 일기사의 공식 소나기 구분과 강도·지속시간을 사용한다.

## 해석 범위

강수 종료 다음날과 시작 전날의 같은 기온 지표를 비교한다. ±0.5°C는 보합이며, 소나기는 하강·약한 지속성은 상승과 일치하는지를 센다. 봄·가을은 3~5월·9~11월로, 사건과 비교일이 같은 계절 범위 안에 있어야 한다. 연중 전체에 봄·가을이 포함된다.

핵심 유형은 소나기 15개·약한 지속성 10개, 봄·가을은 각각 3개·7개다. 이번 기준에 맞는 겨울 액체 강수 사례는 없었다. 이 표본을 한랭·온난전선과 동일시하거나 다른 지역·연도의 법칙으로 일반화하지 않는다. 기사 연결의 7월 19일 예외와 다른 강수 재발의 영향은 리포트에 명시했다.

## 출처와 이용 조건

기상청 기상자료개방포털, ASOS 서울(108), 2024년 시간·일자료, 조회일 **2026-10-27**. 기상청 출처와 [포털의 공공누리 안내](https://data.kma.go.kr/data/grnd/selectAsosRltmList.do?pgmNo=36), [이용 조건](https://www.kogl.or.kr/info/license.do)을 유지한다. 자료가 사후 보정될 수 있어 분석에 사용한 원본도 포함했다. 별도 라이선스를 기상청 자료에 새로 부여하지 않는다.
