# agroai_api/Dockerfile
FROM python:3.11-slim
WORKDIR /app

# Add curl for the ECS health check
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn
COPY app.py .
EXPOSE 80
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80"]
