.PHONY: setup run test clean

setup:
	python -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	python scripts/download-models.py
	cp -n .env.example .env
	mkdir -p data/exports data/logs

run:
	.venv/bin/python -m src.main

test:
	.venv/bin/pytest tests/ -v

clean:
	rm -rf .venv data/ __pycache__ src/**/__pycache__ models/indobert-sentiment/