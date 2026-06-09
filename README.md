# dokkaebi-ai

> 생성형 AI / NPC 서비스. LLM + RAG 파이프라인으로 관광지 데이터를 프롬프트에 주입해 NPC 대사·힌트·사이드퀘스트를 생성.

의존성이 무겁고 LLM 호출 부하에 따라 서버와 다른 주기로 스케일링해야 하므로 별도 컨테이너·레포로 분리합니다.

## Clone

```bash
git clone https://github.com/2026-genai-ar-tourism-data-rpg/dokkaebi-ai.git
cd dokkaebi-ai
```

## 스택

- **런타임**: Python + FastAPI
- **LLM**: LLM SDK (대사·콘텐츠 생성)
- **RAG**: 벡터 DB (pgvector 또는 Qdrant) — 관광지 설명·역사 임베딩
- **검색 증강**: TourAPI 텍스트 데이터(설명·역사·카테고리) 임베딩 후 컨텍스트 검색

## 책임 범위

- 관광지 컨텍스트 RAG 검색 → 프롬프트 실시간 주입
- 관광지 특성에 맞는 NPC 말투·성격별 자연어 대사 생성
- 사용자 진행 상황 기반 개인화 힌트 제공
- 메인 시나리오 유지하면서 관심 장소·방문 이력 분석 → AI 사이드 퀘스트 생성

## 결합 방식

`dokkaebi-server`로부터 **내부 HTTP 요청**을 받아 생성 결과를 반환합니다. 관광지 텍스트 데이터는 DB를 공유해 임베딩/조회합니다.

## 의존 레포

- [`dokkaebi-server`](./dokkaebi-server.md) — 호출 주체, 데이터 소스
