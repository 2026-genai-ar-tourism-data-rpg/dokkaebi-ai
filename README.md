# dokkaebi-ai

> 생성형 AI / NPC 서비스. LangGraph 오케스트레이션으로 관광지 데이터를 프롬프트에 주입해 NPC 대사·힌트·사이드퀘스트를 생성.

의존성이 무겁고 LLM 호출 부하에 따라 서버와 다른 주기로 스케일링해야 하므로 별도 컨테이너·레포로 분리합니다. (배포: 핫패스 = persistent 컨테이너)

---

## 빠른 시작 (개발)

> 요구: **Python 3.11+**

```bash
git clone https://github.com/2026-genai-ar-tourism-data-rpg/dokkaebi-ai.git
cd dokkaebi-ai

# 1) 가상환경 생성 & 활성화
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2) 의존성 설치
pip install -r requirements.txt

# 3) 환경변수 준비 (접두사 DOKKAEBI_)
cp .env.example .env               # 키 없이도 LLM_PROVIDER=mock 으로 구동됨

# 4) 서버 실행
uvicorn app.main:app --reload --port 8001
#  → http://localhost:8001/v1/health  /  POST /v1/dialogue
```

### 스모크 테스트 (그래프 E2E, 키 불필요)

```bash
python3 -c "
import asyncio
from app.services.dialogue_service import run_dialogue
print(asyncio.run(run_dialogue('jongno_unhyeongung', '등장', {})))
"
# → ('[mock 도깨비] 허허, 아직 진짜 LLM이 붙지 않았느니라.', False)
```

> `.venv` / `.env` / `__pycache__` 는 `.gitignore` 처리됨. 커밋 금지.

---

## 디렉터리 구조

```
app/
├── main.py                 FastAPI 엔트리 (uvicorn app.main:app)
├── config.py               설정(SSOT): 세마포어·재시도·백오프·지역캐시 수치
├── core/                   ── 공통 모듈 ──
│   ├── logger.py             공통 로거 팩토리
│   ├── concurrency.py        세마포어 기반 병렬 처리(bounded_gather)
│   └── exceptions.py         도메인 예외(LLMRateLimitError 등)
├── llm/                    ── LLM 레이어 ──
│   ├── base.py               LLMProvider 추상 인터페이스
│   ├── client.py             세마포어 + 429 백오프 재시도 + 병렬 호출 래퍼
│   └── providers/mock.py     키 없이 구동용 목 프로바이더
├── pipeline/               ── LangGraph 오케스트레이션 ──
│   ├── state.py              DialogueState (노드 간 공유 state)
│   ├── graph.py              StateGraph 조립 (조건 엣지: 캐시히트/RAG 분기)
│   └── nodes/                노드 함수 (persona_inject·context_load·retrieve·
│                             prompt_assemble·generate·cache)
├── region/                 ── 런타임 핫 계층 ──
│   └── memory_cache.py       지역 인메모리 캐시(존 서버 패턴, LRU)
├── api/                    routes(엔드포인트) · schemas(요청/응답)
└── services/               dialogue_service(그래프 invoke 래핑)
```

**파이프라인 흐름** (아키텍처 3절):
`persona_inject → cache_read ─(hit)→ END / (miss)→ context_load ─(use_rag?)→ retrieve → prompt_assemble → generate → cache_write → END`

---

## 스택 & 설계 원칙

- **런타임**: Python · FastAPI · **LangGraph**(오케스트레이션, LangChain 풀세트 ❌)
- **grounding 기본 = 그 장소 텍스트 직접 주입**(지역 인메모리). **RAG/임베딩/벡터DB는 옵션**(대형 텍스트·교차검색).
- **LLM**: `LLMClient` 추상화 — 호출 로직(세마포어·429 백오프·병렬)은 한 곳에 통일, provider만 교체.
  - **OpenAI 호환(Upstage Solar·OpenAI 등) 끼리 교체 = config/.env만** (파일 0개): `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`
  - **비호환(HyperCLOVA/Claude 등) 추가 = 파일 1개**: `app/llm/providers/<name>.py` 작성 + `app/llm/client.py::_build_provider`에 한 줄 분기
  - 실서비스 기본 = **Upstage Solar**(`provider=upstage`, `model=solar-pro`). 키 없으면 `provider=mock`으로 구동.

## 책임 범위

- NPC 대사·개인화 힌트 생성 (장소 텍스트 grounding)
- (옵션) RAG 교차검색, AI 사이드 퀘스트·시나리오 사전생성(배치)

## 코딩 컨벤션 (이 레포 필수)

- 파일 맨 위 **헤더 주석**: `[v1]` · 역할 · 파이프라인 위치 · 구현 요약 · 구현일
- **함수마다 역할 주석**, 모듈 최대 분리, 매직넘버는 `config.py`로
- 브랜치 `<기능>/<이름>/<버전>` (예: `base-pipeline/kys/v1`), `dev`로 PR
- API/LLM 호출은 **세마포어(config) + 병렬 + 429 백오프** 필수
- 상세: 조직 `.github` 레포 `CONTRIBUTING.md` · `report/개발계획.md`

## 결합 방식

`dokkaebi-server`로부터 **내부 HTTP**(`POST /v1/dialogue`)를 받아 생성 결과 반환. 앱은 AI 서버를 직접 호출하지 않음(게임 서버 경유).
