FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 reelbot

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=reelbot:reelbot . .

USER reelbot
ENV LOG_FILE= PYTHONUNBUFFERED=1
# Keep yt-dlp current on every start; Instagram breaks old versions often.
CMD ["sh", "-c", "pip install --user -q -U yt-dlp; exec python bot.py"]
