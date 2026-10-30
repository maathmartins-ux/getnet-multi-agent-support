# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS deps
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

FROM deps AS runtime
RUN useradd -m -u 10001 appuser
COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data
COPY evals ./evals
RUN pip install --no-deps -e .
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"
CMD ["uvicorn", "getnet_agents.api:app", "--host", "0.0.0.0", "--port", "8000"]
