FROM python:3.11-slim
WORKDIR /app

# Needed for ECS health check (curl)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Run FastAPI on 0.0.0.0:80
EXPOSE 80
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "80"]
