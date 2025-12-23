FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (only if your requirements need compiling)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
  && rm -rf /var/lib/apt/lists/*

# Python deps
COPY agroai_api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App code
COPY agroai_api/ /app/agroai_api/

# Shim module at repo root so `import agroai` works
COPY agroai/ /app/agroai/
# optional (only if you still need the CLI file in the image)
COPY agroai_cli.py /app/agroai_cli.py

# Make /app importable
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

