FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY bot/requirements.txt ./bot/

RUN pip install --no-cache-dir -r bot/requirements.txt

COPY bot/ ./bot/
COPY shared/ ./shared/
COPY tracker/ ./tracker/
COPY alembic.ini ./

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "bot.main"]
