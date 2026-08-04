#!/bin/bash
# Helper script untuk menjalankan scraper dengan virtual environment

if [ ! -d "venv" ]; then
    echo "Virtual environment 'venv' tidak ditemukan. Menjalankan setup..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
    ./venv/bin/playwright install chromium
fi

source venv/bin/activate
python main.py "$@"
