# --- Tailwind CSS build stage -------------------------------------------------
# Standalone Tailwind v4 CLI (no Node). Version and per-arch sha256 are pinned
# to the GitHub release's sha256sums.txt.
FROM debian:bookworm-slim AS tailwind

ARG TAILWIND_VERSION=4.3.3
ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) ASSET=tailwindcss-linux-x64; SHA=dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a ;; \
        arm64) ASSET=tailwindcss-linux-arm64; SHA=55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195 ;; \
        *) echo "Unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/${ASSET}"; \
    echo "${SHA}  /usr/local/bin/tailwindcss" | sha256sum -c -; \
    chmod +x /usr/local/bin/tailwindcss

WORKDIR /src
COPY assets/ assets/
COPY templates/ templates/
COPY static/ static/
COPY core/ core/
RUN tailwindcss -i assets/tailwind/input.css -o static/css/app.css --minify

# --- Application image ---------------------------------------------------------
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
COPY --from=tailwind /src/static/css/app.css /app/static/css/app.css

# Static assets collected with a throwaway settings/env; no DB needed.
RUN DJANGO_SETTINGS_MODULE=config.settings.dev \
    DATABASE_URL=postgis://x:x@localhost/x \
    python manage.py collectstatic --noinput

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
