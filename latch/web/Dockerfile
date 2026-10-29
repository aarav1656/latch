# Latch hosted app: paste a GitHub PR URL, get the issue-anchored proof receipt.
#
#   docker buildx build --platform linux/amd64 -f latch/web/Dockerfile -t latch-web .   (context = repo root)
#   docker run --rm -p 8080:8080 -e NEBIUS_API_KEY -e GITHUB_TOKEN latch-web
#
# The image carries no secrets. NEBIUS_API_KEY (and optionally GITHUB_TOKEN) are runtime env only.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: clone/archive the PR commits. util-linux: `unshare` for the network-less test phase.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates util-linux \
 && rm -rf /var/lib/apt/lists/* \
 && pip install "uv>=0.5,<1" pytest semver

# Prewarmed wheel cache used by the sandbox (copied per run, so one PR cannot poison another).
# It holds pytest, semver and the common build backends, so most setups never touch the network.
ENV LATCH_UV_CACHE=/opt/latch/uv-cache
RUN mkdir -p /opt/latch \
 && UV_CACHE_DIR=/opt/latch/uv-cache uv venv /tmp/warm \
 && UV_CACHE_DIR=/opt/latch/uv-cache uv pip install --python /tmp/warm/bin/python \
      pytest semver flit_core hatchling setuptools wheel poetry-core pdm-backend \
 && rm -rf /tmp/warm \
 && chmod -R a+rX /opt/latch

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin latch \
 && mkdir -p /data && chown latch:latch /data

WORKDIR /app
COPY latch/ /app/latch/
RUN chmod -R a+rX /app

USER latch
ENV PORT=8080 \
    LATCH_DATA=/data \
    LATCH_LOCAL_KEY_FALLBACK=0 \
    LATCH_TRUST_PROXY=1 \
    PYTHONPATH=/app
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8080'),timeout=2)"
CMD ["python", "-m", "latch.web.app"]
