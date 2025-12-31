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

# Install Python deps from the file you are actually maintaining
COPY terraform/requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip \
    && pip install -r /app/requirements.txt \
    && python -c "import matplotlib; print('matplotlib OK')" \
    && python -c "import matplotlib; import matplotlib.pyplot as plt; print('pyplot OK')"

# Copy app code
COPY . /app

EXPOSE 8000

CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

