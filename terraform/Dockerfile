FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg

WORKDIR /app

# OS libs needed for matplotlib rendering + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      libfreetype6 \
      libpng16-16 \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy BOTH requirements files (whichever one your pipeline actually uses, matplotlib will be installed)
COPY agroai_api/requirements.txt /app/requirements_api.txt
COPY terraform/requirements.txt  /app/requirements_tf.txt

RUN python -m pip install --upgrade pip \
    && pip install -r /app/requirements_api.txt -r /app/requirements_tf.txt \
    && python -c "import matplotlib; print('matplotlib OK')" \
    && python -c "import matplotlib.pyplot as plt; print('pyplot OK')"

# Copy full repo (needs build context = repo root)
COPY . /app

EXPOSE 8000
CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

