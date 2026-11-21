# 1. The dashboard: React built with Node. Only the built files go into the image.
FROM node:24-slim AS dashboard
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite writes to ../ticketbot/web/static, i.e. /src/ticketbot/web/static
RUN npm run build

# 2. The Python packages, in a virtual environment copied into the final image
FROM python:3.14-slim AS packages
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. What runs: Python, the packages, the bot and the built dashboard (no Node, no npm)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    DATA_DIR=/app/data \
    LEGACY_CONFIG=/app/data/config.json

WORKDIR /app
RUN useradd --create-home --uid 1000 ticketbot \
    && mkdir -p /app/data && chown ticketbot:ticketbot /app/data

COPY --from=packages /opt/venv /opt/venv
COPY ticketbot/ ticketbot/
COPY --from=dashboard /src/ticketbot/web/static/ ticketbot/web/static/

USER ticketbot
VOLUME ["/app/data"]
EXPOSE 8080

# The bot; the web dashboard is the same image with `python -m ticketbot web`
CMD ["python", "-m", "ticketbot"]
