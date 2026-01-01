FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    PYTHONPATH=/app

WORKDIR /app

# System libs needed for matplotlib + healthcheck curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libfreetype6 \
    libpng16-16 \
    fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

# Install python deps first (cache-friendly)
COPY agroai_api/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt \
 && python -c "import matplotlib; import matplotlib.pyplot as plt; print('matplotlib OK', matplotlib.__version__)"

# Copy app code
COPY . /app

# Ensure charts directory exists for StaticFiles mount
RUN mkdir -p /app/agroai/charts

EXPOSE 8000
CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

