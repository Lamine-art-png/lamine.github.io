FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app

# Make sure "app" is a proper Python package
# (If app/__init__.py does not exist in your repo, create an empty one there.)
# Here we assume it's already present in the repo.

# Runtime env
ENV PORT=8000
ENV HEALTH_CHECK_PATH=/healthz

# Start FastAPI with the correct module path
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
