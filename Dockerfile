FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY data/ data/
EXPOSE 8000
CMD python -m backend.seed; python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}
