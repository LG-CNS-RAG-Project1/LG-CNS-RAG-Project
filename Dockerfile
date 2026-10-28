# syntax=docker/dockerfile:1

# 애플리케이션 실행 의존성(requirements.txt)을 설치하는 공통 Python 이미지
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 포매터·테스트 도구를 추가하고 소스 코드를 바인드 마운트로 사용하는 개발 이미지
FROM base AS dev

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory /app

COPY requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-dev.txt

ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home app
USER app

CMD ["sleep", "infinity"]
