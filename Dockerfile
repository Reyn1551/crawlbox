FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ libxml2-dev libxslt1-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY static/ static/
COPY scripts/ scripts/
COPY templates/ templates/
RUN mkdir -p /app/data/exports /app/data/logs /app/models
EXPOSE 8000
CMD ["python","-m","src.main"]