# agroai_api/Dockerfile
FROM python:3.11-slim
WORKDIR /app

# curl is needed for the ECS health check command in your task def
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy the app
COPY . .

# expose and run FastAPI on 0.0.0.0:80
EXPOSE 80
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "80"]
