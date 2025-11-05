FROM python:3.11-slim
WORKDIR /app

# curl is required by the ECS health check command
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn

# copy your app file
COPY agroai_api/app/app.py /app/app.py

ENV PORT=80
EXPOSE 80
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","80"]
