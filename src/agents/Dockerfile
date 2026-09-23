FROM python:3.14.6-slim AS base

# Install system dependencies required by LiveKit
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then sed -i -e 's@http://deb.debian.org@https://mirrors.cloud.tencent.com@g' -e 's@http://security.debian.org@https://mirrors.cloud.tencent.com@g' /etc/apt/sources.list.d/debian.sources; fi \
    && apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgobject-2.0-0 \
    && rm -rf /var/lib/apt/lists/*


# ---- Builder image ----
FROM base AS builder

ARG UV_DEFAULT_INDEX=https://mirrors.cloud.tencent.com/pypi/simple

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Install uv
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple uv==0.10.9

WORKDIR /app

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv lock && uv sync --locked --no-dev


# ---- Development image ----
FROM base AS development

ARG UV_DEFAULT_INDEX=https://mirrors.cloud.tencent.com/pypi/simple

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple uv==0.10.9

WORKDIR /app

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv lock && uv sync --locked --all-extras

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "multi_user_transcriber.py", "dev"]


# ---- Production image ----
FROM base AS production

WORKDIR /app

# Copy the pre-built virtualenv and application source
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

# Remove pip to reduce attack surface in production
RUN pip uninstall -y pip

# Un-privileged user running the application
ARG DOCKER_USER
USER ${DOCKER_USER}

CMD ["python", "multi_user_transcriber.py", "start"]
