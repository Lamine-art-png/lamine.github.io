FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# (Optional but useful) basic OS deps for building some Python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Install Python deps (adjust path if your requirements.txt lives elsewhere)
COPY agroai_api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the API code
COPY agroai_api/ /app/agroai_api/

# ✅ Copy the missing module into the image root
COPY agroai.py /app/agroai.py

# ✅ Make /app importable so "import agroai" works
ENV PYTHONPATH=/app

EXPOSE 8000

# Start the API (matches /app/agroai_api/app/main.py)
CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

