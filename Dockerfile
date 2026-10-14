# Home Headquarters container for Google Cloud Run (FND-03).
FROM python:3.13.7-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Static files are collected at build time; these placeholder values never reach the running app.
RUN DJANGO_SECRET_KEY=build-only-placeholder DATABASE_URL=postgresql://build@localhost/build \
    python manage.py collectstatic --noinput
RUN useradd --create-home --uid 10001 app
USER app
# Migrations run as a separate Cloud Run job during deploy, so cold starts stay fast.
CMD exec gunicorn hq.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 60
