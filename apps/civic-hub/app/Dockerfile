# civic-hub — collector (CronJob) and web (Deployment) share this image.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin civic
COPY civic_hub ./civic_hub
USER 10001
EXPOSE 8080
CMD ["uvicorn", "civic_hub.web:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
