FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ffmpeg \
  && rm -rf /var/lib/apt/lists/*

COPY agroai_api/requirements.txt /app/agroai_api/requirements.txt
RUN pip install --upgrade pip \
  && pip install -r /app/agroai_api/requirements.txt

COPY agroai/ /app/agroai/
COPY agroai_api/ /app/agroai_api/
COPY shared/ /app/shared/

ENV PYTHONPATH=/app:/app/agroai_api

EXPOSE 8000

WORKDIR /app/agroai_api
CMD ["sh", "/app/agroai_api/start-production.sh"]

ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA
