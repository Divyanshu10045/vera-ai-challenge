# Vera — Merchant AI Assistant

## Overview
A stateful merchant engagement assistant built for the magicpin Vera AI Challenge.

## API
Public deployment:
https://vera-ai-challenge-49oz.onrender.com/

Endpoints:
- GET  /v1/healthz
- GET  /v1/metadata
- POST /v1/context
- POST /v1/tick
- POST /v1/reply

## Local Development

pip install -r requirements.txt

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

## Testing

python -m pytest -q
