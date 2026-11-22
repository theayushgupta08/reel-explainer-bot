@echo off
cd /d "%~dp0"
if not exist .venv (
    py -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python -m pip install -U yt-dlp --quiet
.venv\Scripts\python bot.py
pause
