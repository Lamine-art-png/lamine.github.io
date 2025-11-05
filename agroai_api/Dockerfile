# agroai_api/Dockerfile
FROM python:3.11-slim
WORKDIR /app

# deps + curl for ECS health check
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && apt-get update && apt-get install -y curl \
 && rm -rf /var/lib/apt/lists/*

# app code
COPY app/ app/

# container port
ENV PORT=80
EXPOSE 80

# FastAPI via Uvicorn; note module path: app/app.py -> "app.app:app"
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "80"]
