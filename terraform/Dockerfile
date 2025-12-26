FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg

WORKDIR /app

# Minimal OS libs commonly needed (matplotlib + fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libfreetype6 \
    libpng16-16 \
    fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better caching
# IMPORTANT: this path assumes the build context is repo root and agroai_api/ exists
COPY agroai_api/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install -r /app/requirements.txt

# Copy app code
COPY . /app

EXPOSE 8000

# Start API
CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

