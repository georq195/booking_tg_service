FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Зависимости отдельным слоем: кэш не сбрасывается при правке кода
COPY requirements.txt .
RUN pip install -r requirements.txt

# Не root; /app/data создаётся заранее, чтобы том унаследовал владельца
RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/data \
    && chown bot:bot /app/data

COPY --chown=bot:bot app ./app

USER bot

CMD ["python", "-m", "app.main"]
