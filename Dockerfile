FROM python:3.11-slim

# Basics
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Optional but handy for debugging/health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better build caching)
COPY agroai_api/requirements.txt /app/agroai_api/requirements.txt
RUN pip install --upgrade pip \
  && pip install -r /app/agroai_api/requirements.txt

# Copy application code
# IMPORTANT: copy the PACKAGE DIR (agroai/), NOT a file named agroai.py
COPY agroai/ /app/agroai/
COPY agroai_api/ /app/agroai_api/
# If you have a CLI script and want it in the image:
# COPY agroai_cli.py /app/agroai_cli.py

# Make repo root importable: allows `import agroai` and `import agroai_api`
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

