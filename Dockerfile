FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY bracis/ /app/bracis/
COPY run.py /app/run.py

ENTRYPOINT ["python", "/app/run.py"]
