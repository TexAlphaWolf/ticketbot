FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    LEGACY_CONFIG=/app/data/config.json

WORKDIR /app

RUN useradd --create-home --uid 1000 ticketbot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ticketbot/ ticketbot/
RUN mkdir -p /app/data && chown ticketbot:ticketbot /app/data

USER ticketbot
VOLUME ["/app/data"]

CMD ["python", "-m", "ticketbot"]
