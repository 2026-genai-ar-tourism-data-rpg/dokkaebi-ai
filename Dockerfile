# [v1] dokkaebi-ai 컨테이너 이미지 (base-pipeline/kys/v1, 2026-06-10)
# pipeline: 배포 — 핫패스 persistent 컨테이너(아키텍처 9절)
FROM python:3.11-slim

WORKDIR /app

# 의존성 먼저(레이어 캐시)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스
COPY app ./app

EXPOSE 8001
# uvicorn으로 FastAPI 기동 (env는 compose/.env에서 DOKKAEBI_* 주입)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
