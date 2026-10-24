FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# GeoDjango runtime libraries (GDAL, GEOS, PROJ) + a couple of utilities.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gdal-bin \
        libgdal-dev \
        libgeos-c1v5 \
        libproj25 \
    && rm -rf /var/lib/apt/lists/*

ARG REQUIREMENTS=requirements/base.txt
COPY requirements/ /app/requirements/
RUN pip install --no-cache-dir -r /app/${REQUIREMENTS}

WORKDIR /app
COPY . /app

# Static assets collected with a throwaway settings/env; no DB needed.
RUN DJANGO_SETTINGS_MODULE=config.settings.dev \
    DATABASE_URL=postgis://x:x@localhost/x \
    python manage.py collectstatic --noinput

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
