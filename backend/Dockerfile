FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so the first start does not download ~80 MB.
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as D; D()(['warm up'])"

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
# One worker on purpose: the rate limiter and ChromaDB state are per-process.
CMD ["./docker-entrypoint.sh"]
