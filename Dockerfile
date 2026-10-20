# Image officielle Playwright : Python + Chromium déjà installés.
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Dossier persistant (monté en volume) pour nouris_watch.json / history.jsonl
RUN mkdir -p /app/data && cp /app/nouris_watch.json /app/data/nouris_watch.json && chmod -R 777 /app
ENV DATA_DIR=/app/data

EXPOSE 7860

ENV PYTHONUNBUFFERED=1
ENV TZ=Africa/Algiers
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

CMD ["python", "app.py"]
