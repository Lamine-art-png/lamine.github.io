FROM python:3.11-slim
WORKDIR /app
COPY ./agroai_api /app/agroai_api
COPY ./agroai_api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true
COPY ./requirements.txt /app/root-reqs.txt
RUN [ -f /app/root-reqs.txt ] && pip install --no-cache-dir -r /app/root-reqs.txt || true
EXPOSE 80
CMD ["python","-c","import uvicorn; uvicorn.run('agroai_api.main:app', host='0.0.0.0', port=80)"]
