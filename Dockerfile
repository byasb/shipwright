FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY shipwright ./shipwright
COPY main.py ./
RUN pip install --no-cache-dir .
# The .p8 is NEVER copied in: it is read from Secret Manager at runtime (see shipwright/config.py).
ENV PORT=8080 PYTHONUNBUFFERED=1
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 75
