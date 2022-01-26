# --- build the React frontend ------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- API + static files ----------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sqlchat ./sqlchat
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN useradd --create-home app
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
ENTRYPOINT ["python", "-m", "sqlchat", "--log-level", "INFO"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
ENV DECODE_PAYLOAD=true
ENV SAVE_STATE=true
ENV DECODE_PAYLOAD=true