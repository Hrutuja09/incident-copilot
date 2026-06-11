FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml .
RUN uv pip install --system --no-cache \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.30.0" \
    "structlog>=24.1.0" \
    "pydantic>=2.0.0" \
    "httpx>=0.27.0"

COPY . .

EXPOSE 8001

CMD ["uvicorn", "copilot.main:app", "--host", "0.0.0.0", "--port", "8001"]
