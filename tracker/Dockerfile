FROM python:3.12-slim

WORKDIR /app

COPY tracker/requirements.txt ./tracker/

RUN pip install --no-cache-dir -r tracker/requirements.txt

COPY tracker/ ./tracker/
COPY shared/ ./shared/
COPY bot/ ./bot/
COPY alembic.ini ./

ENV PYTHONPATH=/app

CMD ["python", "-m", "tracker.main"]
