# 서울 ASOS 강수 기록과 기온 변화 분석

과제 결과는 [REPORT.md](REPORT.md)에 있다. 분석은 기상청 서울 관측소(108)의 **2024년 전체 시간자료 8,784개**를 사용한다. 연간 기온 흐름은 1~12월, 같은 관측 간격의 강수 강도·기온 비교는 4~10월로 나눈다.

## 실행

Python **3.10 이상**이 필요하다. 분석 코드는 표준 라이브러리만 사용하며 제3자 패키지 설치가 필요 없다. 작성·검증 환경은 Python 3.14.7이다.

```powershell
python analysis.py
python scripts/audit_asos.py
```

첫 명령은 `metrics.json`과 `images/`의 SVG 그래프 3개를 다시 만든다. 두 번째 명령은 원본 행 수, 시각 연속성, 강수값·QC 플래그 상태를 점검한다. 원본 CSV는 CP949 인코딩으로 읽는다.

## 파일

```text
.
├─ analysis.py
├─ data/raw/seoul_asos_hourly_2024.csv
├─ data/raw/seoul_asos_hourly_2024-06_09.csv  # 초기 범위 검증용
├─ images/
│  ├─ 01_temperature_timeline.svg
│  ├─ 02_rain_intensity_delta1_adjusted.svg
│  └─ 03_delta24_by_month.svg
├─ metrics.json
├─ REPORT.md
├─ PRD.md
├─ requirements.txt
└─ scripts/audit_asos.py
```

## 원본을 다시 받는 방법

1. [기상청 기상자료개방포털 ASOS 자료](https://data.kma.go.kr/data/grnd/selectAsosRltmList.do?pgmNo=36)에 로그인한다.
2. `시간 자료`를 선택하고 기간을 `2024-01-01 00시`~`2024-12-31 23시`로 지정한다.
3. 지점 `서울(108)`과 요소 `기온`, `기온 QC플래그`, `강수량`, `강수량 QC플래그`를 선택한다.
4. 조회 후 CSV를 내려받는다. 원본은 수정하지 말고 `data/raw/`에 놓는다. 재현 시 이 저장소의 원본 파일명으로 맞춘다.

자료 출처는 **기상청 기상자료개방포털, 종관기상관측(ASOS) 시간자료, 서울(108), 2024-01-01~2024-12-31, 조회일 2026-10-27**이다. 포털 하단의 공공누리 출처표시 안내와 [이용 조건](https://www.kogl.or.kr/info/license.do)을 확인하고 출처를 유지해야 한다. 자료가 사후 보정되면 같은 조건으로 다시 받은 파일의 수치가 달라질 수 있으므로, 이 저장소에는 분석에 사용한 원본도 포함했다.

## 해석 범위

강수량 공란을 무강수 `0`으로 일괄 변환하지 않는다. QC 플래그 `9`는 결측이며, 플래그 없는 공란의 의미는 추가 확인이 필요하다. 기상청은 11월~3월 강수량을 3시간 간격으로 제공하므로 그 기간을 4~10월의 시간당 강도 구간과 합치지 않는다. 결과는 **강수량 양수 기록 시각**을 기준으로 한 기술 분석이다. 실제 강수 종료 시각, 전선·구름의 종류, 강수가 기온을 바꾼 인과 효과를 주장하지 않는다.
