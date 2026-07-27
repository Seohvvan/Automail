# 검색 신뢰성 · 승인 제어 개선 설계

- 날짜: 2026-07-27
- 대상 브랜치: AgentDeploy
- 상태: 설계 확정 (구현 전)

## 배경

automail 운영 중 다음 문제들이 확인되었다. 각 항목은 실제 코드 추적 및 라이브 사이트 실측으로 근본 원인을 규명했다.

1. **검색 시도 횟수가 남은 채 승인 단계로 진입** — supervisor(LLM)가 `MAX_SEARCH_ATTEMPTS(2)`를 다 쓰기 전에 `approve_send`를 선택해, 미발견 업체의 재검색이 승인 이후로 미뤄진다. (로그 실증: `#2 ... 검색 시도 횟수가 1회로 남아있어` 상태로 승인 화면 도달)
2. **"발송 건너뛰기" 후 재탐색 발생** — 승인 대기 재개(resume) 시 남은 시도 횟수로 재검색이 돌아, 사용자가 "그만"의 의도로 누른 동작이 추가 작업을 유발한다.
3. **수동 입력 이메일 소실** — 승인 대기 중 사람이 시트에 직접 넣은 이메일이, 완료 시 메모리 상태(빈 값)로 덮어써져 사라질 수 있다.
4. **정적 HTML로 못 잡는 이메일** — JS 렌더링 사이트(예: farmtc365.com)는 이메일이 정적 HTML에 없어 구조적으로 미발견된다.
5. **환각/오합성** — 유사 상호·업종을 근거로 다른 업체 이메일을 매칭(예: 휘프레시 → 지푸드프레시의 `gfoodfresh@naver.com`을 HIGH로 오판정).
6. **`.` 포함 이메일 잘림** — `luckyfresh.official@gmail.com`이 `official@gmail.com`으로 잘려 추출된다.

### 실측 근거 (2026-07-27)

- **farmtc365.com**: 정적 fetch(24,443자)에 `farmtc365` 문자열조차 없음 → JS 삽입. Jina Reader는 `farmtc365@naver.com`을 정상 추출. Tavily Extract는 실패(렌더링 못 함).
- **luckyfresh.co.kr**: 이메일이 JS 번들(`index-ssWDL764.js`, 1.34MB)에 문자열로 박혀 있음(`개인정보책임자 : 최승준(luckyfresh.official@gmail.com)`). 정적 fetch·Jina 모두 footer 미포함으로 못 잡음 → **번들 스캔만이 유일한 경로**. 같은 번들에 플레이스홀더 `example@company.com`도 존재.
- **잘림 재현**: 정규식은 깔끔한 텍스트에선 점 포함 로컬파트를 온전히 추출. 로컬파트 중간에 마크업(`luckyfresh<span>.</span>official@...`, `<wbr>`)이 끼면 `official@gmail.com`으로 잘림. **태그 제거 후 regex를 돌리면 온전히 복구됨**(검증 완료).

## 목표 / 비목표

**목표**
- 미발견 업체를 승인 전에 시도 횟수까지(또는 발견까지) 확실히 재검색한다.
- "발송 건너뛰기"는 재검색 없이 종료한다.
- 수동 입력 이메일이 덮어써지지 않게 보호한다.
- JS 렌더링/번들 사이트의 이메일을 단계적 폴백으로 회수한다.
- 다른 업체 정보의 임의 합성과 플레이스홀더 이메일을 차단한다.
- 마크업으로 인한 이메일 잘림을 없앤다.

**비목표**
- 로컬 헤드리스 브라우저 도입(Streamlit Cloud 제약으로 배제).
- 검색 에이전트의 전면 재설계(ReAct 구조 유지).
- 답장/후속 대응 흐름 변경.

## 설계

### 그룹 A — 승인 제어 흐름 (`agents/supervisor.py`, `automail_st.py`)

#### A1. 검색 소진 게이트 (문제 1)
- `supervisor_node`에 결정적 게이트를 추가한다: **email이 비어 있는(미발견) 업체 중 `search_attempts < MAX_SEARCH_ATTEMPTS`인 대상이 하나라도 있으면 `approve_send` 및 `finish`를 허용하지 않고 `search`로 강제 전환.**
- 적용 지점: LLM 결정 검증부([supervisor.py:151-157](../../../agents/supervisor.py) 부근). LLM이 approve_send/finish를 골라도 미소진 검색 대상이 있으면 오버라이드한다.
- "발견(성공)" 기준 = **email 필드가 채워짐**(HIGH/REVIEW 무관). 빈 값(NONE)만 소진 대상.
- 기존 `_fallback` 우선순위(search 최우선)와 일관.

#### A2. "발송 건너뛰기" = 종료 (문제 2)
- resume 페이로드에 `stop` 플래그 추가. `automail_st.py`의 "발송 건너뛰기" 버튼([automail_st.py:912-915](../../../automail_st.py))이 `{"approved": [], "stop": True}` 전송.
- `approve_send_node`가 `stop`을 받으면 상태에 `_stop=True`를 세팅하고 supervisor로 복귀.
- `supervisor_node`는 `_stop`이 True면 다른 판단 없이 즉시 `finish`.
- A1로 이미 검색이 소진돼 자연 종료되는 경우가 많지만, 이 플래그로 **명시적으로 보장**한다.
- "선택한 업체 발송 승인" 버튼은 `stop`을 보내지 않으므로 기존 동작 유지.

#### A3. 덮어쓰기 가드 (문제 3)
- `_persist_auto_rows`([automail_st.py:535-545](../../../automail_st.py))가 시트에 email 열을 쓸 때, **메모리 email이 비어 있으면 시트의 기존 값을 `""`로 덮지 않는다.** 즉 비어 있지 않은 시트 값은 보존(병합).
- 제목/본문 열은 현행 동작 유지(초안은 실행 산출물이므로 덮어쓰기 정상).
- 효과: 승인 대기 중 사람이 시트에 넣은 이메일이 재검색 실패/완료 시 사라지지 않는다.

### 그룹 B — 검색 신뢰성 (`agents/tools.py`, `agents/search_agent.py`)

#### B1. HTML→텍스트 정규화 후 추출 (문제 6)
- 공용 정규화 함수 도입: `<[^>]+>` 제거 + 공백 정규화 → 그 결과에 `EMAIL_RE`/`CandidateStore.add_from_text` 적용.
- 현재 raw HTML에서 추출하는 지점([tools.py:212·215](../../../agents/tools.py))을 정규화된 텍스트 기반으로 교체.
- 모든 경로(정적/Jina/번들)가 동일 정규화를 거친다.
- 실제 공백으로 분리된 토큰(`luckyfresh. official@...`)은 합치지 않는다(별개 주소가 맞음).

#### B2. 2단 렌더링 폴백 (문제 4)
`open_website`를 단계적 폴백으로 확장한다. **각 단계는 이전 단계가 이메일 후보 0개일 때만** 실행한다.

```
1) urllib 정적 fetch (현행)                       → 후보 추출
2) 후보 0개면 → Jina Reader (r.jina.ai/<원본URL>) → 후보 추출   [farmtc365류 해결]
3) 그래도 0개면 → 페이지에 링크된 .js 번들 스캔    → 후보 추출   [luckyfresh류 해결]
```

- 모든 단계 결과는 동일한 정규화(B1) → regex → `CandidateStore`(도메인 기록) → `_grade` 파이프라인에 태운다.
- Jina: `https://r.jina.ai/<원본URL>` GET, 타임아웃 여유(~40s). 실패 시 조용히 다음 단계.
  선택적 `JINA_API_KEY`(st.secrets/env)가 있으면 인증 헤더로 rate limit 상향.
- 번들 스캔: 정적 HTML의 `<script src>` 중 **동일 도메인 `.js`만**, 파일 개수 상한(기본 5개)·각 크기 상한을 두고 받아 정규화→regex. 번들에서 목격된 이메일은 해당 도메인에서 목격된 것으로 store에 기록.
- 비용 통제: 2·3단계는 정적 실패 시에만 타므로 대부분 사이트에서 호출되지 않는다.

#### B3. 환각/오합성 방지 (문제 5, + B2 부작용 대응)
- `search_agent._SYSTEM`에 규칙 추가:
  > 임의 합성 금지 — 이메일 ID, 유사 상호명, 유사 업종(예: 농산물 유통)이라는 이유만으로 서로 다른 업체의 정보를 하나로 묶거나 합치지 마라. 힌트(업종/지역)와 명확히 불일치하면 `is_target_business=false`로 판단하라.
- `SearchDecision.email` / `is_target_business` 필드 설명도 동일 취지로 강화.
- **플레이스홀더 필터(결정적)**: `CandidateStore.add`에 차단 목록 추가 — 로컬파트가 `example`, `test`, `sample`, `your`, `email`, `noreply`, `no-reply` 등인 후보는 store 진입 거부. (B2 번들 스캔이 유입시키는 `example@company.com` 류 차단; 이들은 공식 도메인에서 목격되므로 필터 없으면 HIGH로 오판정될 수 있음.)
- (검토 항목, 필수 아님) `official_domain`이 업체명/힌트와 명백히 무관할 때 HIGH를 REVIEW로 강등하는 추가 게이트 — 1차 방어는 프롬프트로 두고, 효과가 부족하면 도입.

## 데이터 흐름 변화 요약

- `supervisor`: 매 턴 결정 후 **A1 게이트 → A2 stop 검사** 순으로 최종 액션 확정.
- `open_website`: 단일 정적 조회 → **정적→Jina→번들 3단 폴백**, 공용 정규화 경유.
- `_persist_auto_rows`: email 열 쓰기가 **빈 값 보존(병합)** 방식으로 변경.

## 오류 처리

- Jina/번들 단계의 네트워크·타임아웃 오류는 삼키고 다음 단계 또는 "후보 없음"으로 진행(현행 도구 오류 처리 방침과 동일).
- A1/A2 게이트는 무한 루프를 만들지 않는다: 검색은 `MAX_SEARCH_ATTEMPTS`로 상한, supervisor 턴은 `MAX_STEPS`로 상한.

## 테스트 계획

- **단위**
  - 정규화+regex: 마크업 낀 케이스(`<span>`, `<wbr>`)에서 점 포함 이메일 온전 추출, 실제 공백 케이스는 미합치.
  - 플레이스홀더 필터: `example@company.com` 등 차단, 정상 이메일 통과.
  - A1 게이트: 미발견+시도 잔여 업체가 있으면 approve_send/finish가 search로 오버라이드됨.
  - A2 stop: `_stop=True`면 supervisor가 즉시 finish.
  - A3 병합: 메모리 email 빈 값일 때 시트 기존 값 보존.
- **통합/실측**
  - farmtc365.com → Jina 경로로 `farmtc365@naver.com` 회수.
  - luckyfresh.co.kr → 번들 스캔으로 `luckyfresh.official@gmail.com` 회수, `example@company.com` 미채택.

## 설정 / 시크릿

- `JINA_API_KEY`(선택): st.secrets `[jina]` 또는 환경변수. 없으면 무키 모드로 동작(무료 티어 한도).
- 신규 필수 시크릿 없음.

## 영향 파일

- `agents/supervisor.py` (A1, A2)
- `automail_st.py` (A2 버튼 페이로드, A3 병합)
- `agents/tools.py` (B1 정규화, B2 폴백, B3 플레이스홀더 필터)
- `agents/search_agent.py` (B3 프롬프트/필드)

## 범위 밖

- "자동 실행 시작"(fresh) 모드의 email 초기화 동작 변경(설계상 의도된 재시작이므로 유지).
- 버튼 명칭 변경(별도 UX 개선으로 분리 가능).
