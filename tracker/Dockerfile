FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY tracker/requirements.txt ./tracker/

RUN pip install --no-cache-dir -r tracker/requirements.txt

COPY tracker/ ./tracker/
COPY shared/ ./shared/
COPY bot/ ./bot/
COPY alembic.ini ./

ENV PYTHONPATH=/app

CMD ["python", "-m", "tracker.main"]
