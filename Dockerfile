# One image: FastAPI serves the API and the built React app.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/kaushalniti backend/kaushalniti
COPY data/demo data/demo
COPY data/processed data/processed
COPY data/metadata data/metadata
COPY --from=web /web/dist frontend/dist
USER nobody
EXPOSE 8000
CMD ["uvicorn", "kaushalniti.api:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
