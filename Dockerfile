# Vendor Clearance Desk web UI. Keys come from the environment at run time; none are baked into the image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_MODE=demo APP_DB=/data/clearance.db
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home appuser && mkdir -p /data && chown appuser /data
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
