ARG PYTHON_IMAGE=python:3.12.10-slim-bookworm
ARG UV_VERSION=0.11.7

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime-base

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH=/opt/venv/bin:${PATH} \
    HOME=/home/app

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && install -d -o app -g app -m 1770 /tmp/enterprise-drive

ENV TMPDIR=/tmp/enterprise-drive \
    XDG_CACHE_HOME=/tmp/enterprise-drive/cache

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app scripts ./scripts

USER app

EXPOSE 18080 9100

STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "scripts.runtime_entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18080"]

FROM runtime-base AS runtime

LABEL org.opencontainers.image.title="Enterprise Drive Backend" \
      org.opencontainers.image.description="FastAPI API and Celery worker runtime"

FROM runtime-base AS preview

USER root

RUN apt-get -o Acquire::Retries=5 -o Acquire::http::No-Cache=true update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::No-Cache=true \
        install --no-install-recommends -y \
        fontconfig \
        fonts-dejavu-core \
        fonts-noto-cjk \
        libreoffice-calc \
        libreoffice-core \
        libreoffice-impress \
        libreoffice-writer \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && fc-cache -f \
    && soffice --version \
    && pdftoppm -v \
    && tesseract --version \
    && tesseract --list-langs \
    && tesseract --list-langs 2>/dev/null | grep -Fxq eng \
    && tesseract --list-langs 2>/dev/null | grep -Fxq chi_sim \
    && rm -rf /var/lib/apt/lists/* /var/cache/fontconfig/* \
    && chown -R app:app /tmp/enterprise-drive /home/app

USER app

LABEL org.opencontainers.image.title="Enterprise Drive Preview Worker" \
      org.opencontainers.image.description="Celery content runtime with LibreOffice, Poppler, Tesseract and CJK fonts"
