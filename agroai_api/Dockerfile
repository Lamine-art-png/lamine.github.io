FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
  && rm -rf /var/lib/apt/lists/*

COPY agroai_api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy your packages
COPY agroai/ /app/agroai/
COPY agroai_api/ /app/agroai_api/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["uvicorn", "agroai_api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

