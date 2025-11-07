FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy backend code
COPY agroai_api/ ./agroai_api

# Install deps (adjust path if your requirements file lives elsewhere)
RUN pip install --no-cache-dir -r agroai_api/requirements.txt

# Make agroai_api the import root: "import app" -> /app/agroai_api/app
ENV PYTHONPATH=/app/agroai_api

# Start FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
