#!/usr/bin/env bash
# Deploy Latch web to Nebius Serverless AI (container registry + public endpoint).
#
#   NEBIUS_PROJECT_ID=project-... NEBIUS_REGION=eu-north1 NEBIUS_SUBNET_ID=vpcsubnet-... \
#   NEBIUS_API_KEY=... [GITHUB_TOKEN=...] latch/web/deploy.sh [deploy|build|vercel]
#
# This script NEVER logs you in. Run `nebius profile create` yourself first.
# Nothing here has been run by the author: read it, then run it deliberately.
# Set DRY_RUN=1 to print every mutating command instead of running it.
set -euo pipefail

CMD="${1:-deploy}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

: "${NEBIUS_REGION:=eu-north1}"                 # region of the project (cr.<region>.nebius.cloud)
: "${REGISTRY_NAME:=latch}"
: "${IMAGE_NAME:=latch-web}"
: "${ENDPOINT_NAME:=latch-web}"
: "${PLATFORM:=cpu-d3}"
: "${PRESET:=4vcpu-16gb}"
: "${DISK_SIZE:=}"                              # optional, e.g. 50GiB
: "${ENDPOINT_AUTH:=none}"                      # none = reachable by judges without a token; token = private
: "${UPDATE_MODE:=recreate}"                    # recreate (delete + create, new tag) | restart (same tag re-pushed)
: "${MAX_RUNS_PER_DAY:=50}"                     # LATCH_MAX_LIVE_RUNS_PER_DAY
: "${SECRET_SELECTOR:=}"                        # MysteryBox secret for NEBIUS_API_KEY (preferred over a plain env var)
: "${DRY_RUN:=0}"
: "${IMAGE_TAG:=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"

say() { printf '\n==> %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
run() {
  if [ "$DRY_RUN" = "1" ]; then printf 'DRY_RUN:'; printf ' %q' "$@"; printf '\n'; else "$@"; fi
}
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required but not on PATH"; }

# ---------------------------------------------------------------- vercel fallback
deploy_vercel() {
  need vercel
  local stage; stage="$(mktemp -d)"
  say "Staging a cached-receipts-only Vercel project in $stage"
  mkdir -p "$stage/latch"
  (cd "$REPO_ROOT" && tar --exclude='__pycache__' --exclude='.data' --exclude='test_*.py' \
      -cf - latch/*.py latch/harness/*.py latch/web latch/runs/click-3298.json latch/runs/loop-demo-events.jsonl) \
    | tar -xf - -C "$stage"
  mkdir -p "$stage/api"
  cp "$REPO_ROOT/latch/web/vercel/api/index.py" "$stage/api/index.py"
  printf '{ "rewrites": [ { "source": "/(.*)", "destination": "/api/index" } ] }\n' > "$stage/vercel.json"
  say "Deploying (live runs are off on Vercel; the UI shows the cached receipts)"
  (cd "$stage" && run vercel deploy --prod)
}

if [ "$CMD" = "vercel" ]; then deploy_vercel; exit 0; fi
[ "$CMD" = "deploy" ] || [ "$CMD" = "build" ] || die "usage: deploy.sh [deploy|build|vercel]"

# ---------------------------------------------------------------- preflight
need docker; need nebius; need jq
: "${NEBIUS_PROJECT_ID:?set NEBIUS_PROJECT_ID (the project that will own the registry and endpoint)}"
if [ "$CMD" = "deploy" ]; then
  : "${NEBIUS_SUBNET_ID:?set NEBIUS_SUBNET_ID (nebius vpc subnet list)}"
  if [ -z "$SECRET_SELECTOR" ]; then : "${NEBIUS_API_KEY:?set NEBIUS_API_KEY, or SECRET_SELECTOR to a MysteryBox secret that holds it}"; fi
fi
if ! nebius iam whoami >/dev/null 2>&1; then
  die "the Nebius CLI is not logged in. Run 'nebius profile create' yourself, then re-run this script."
fi

# ---------------------------------------------------------------- registry
say "Looking for container registry '$REGISTRY_NAME' in $NEBIUS_PROJECT_ID"
REGISTRY_ID="$(nebius registry list --parent-id "$NEBIUS_PROJECT_ID" --format json \
  | jq -r --arg n "$REGISTRY_NAME" '.items // [] | map(select(.metadata.name == $n)) | .[0].metadata.id // empty')"
if [ -z "$REGISTRY_ID" ]; then
  say "Creating registry '$REGISTRY_NAME'"
  if [ "$DRY_RUN" = "1" ]; then
    run nebius registry create --name "$REGISTRY_NAME" --parent-id "$NEBIUS_PROJECT_ID" --format json
    REGISTRY_ID="registry-DRYRUN"
  else
    REGISTRY_ID="$(nebius registry create --name "$REGISTRY_NAME" --parent-id "$NEBIUS_PROJECT_ID" --format json | jq -r '.metadata.id')"
  fi
fi
REGISTRY_PATH="$(printf '%s' "$REGISTRY_ID" | cut -d- -f2)"      # registry id without the 'registry-' prefix
REGISTRY_HOST="cr.${NEBIUS_REGION}.nebius.cloud"
IMAGE="${REGISTRY_HOST}/${REGISTRY_PATH}/${IMAGE_NAME}:${IMAGE_TAG}"
say "Image: $IMAGE"

# ---------------------------------------------------------------- docker login + build + push
# Short-lived access token (12 h), per https://docs.nebius.com/container-registry/authentication.md
# (alternative on a workstation: `nebius registry configure-helper`, then no login is needed).
say "Logging Docker in to $REGISTRY_HOST (token piped from the already-authenticated CLI)"
if [ "$DRY_RUN" = "1" ]; then
  echo "DRY_RUN: nebius iam get-access-token | docker login $REGISTRY_HOST --username iam --password-stdin"
else
  nebius iam get-access-token | docker login "$REGISTRY_HOST" --username iam --password-stdin
fi

say "Building for linux/amd64 (context = repo root) and pushing"
# Colima/Docker data lives wherever your daemon is configured; keep it off a nearly-full disk.
run docker buildx build --platform linux/amd64 -f "$REPO_ROOT/latch/web/Dockerfile" -t "$IMAGE" --push "$REPO_ROOT"
[ "$CMD" = "build" ] && { echo "$IMAGE"; exit 0; }

# ---------------------------------------------------------------- endpoint
say "Looking for endpoint '$ENDPOINT_NAME'"
EXISTING_ID="$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" --parent-id "$NEBIUS_PROJECT_ID" --format json 2>/dev/null \
  | jq -r '.metadata.id // empty' || true)"

if [ -n "$EXISTING_ID" ]; then
  if [ "$UPDATE_MODE" = "restart" ]; then
    # Only valid when you re-pushed the SAME tag (set IMAGE_TAG explicitly). Not verified by the author.
    say "Restarting $EXISTING_ID so it pulls the re-pushed image"
    run nebius ai endpoint restart --id "$EXISTING_ID"
    ENDPOINT_ID="$EXISTING_ID"
  else
    say "Deleting old endpoint $EXISTING_ID (its URL will change)"
    run nebius ai endpoint delete --id "$EXISTING_ID"
    EXISTING_ID=""
  fi
fi

if [ -z "$EXISTING_ID" ]; then
  say "Creating endpoint '$ENDPOINT_NAME' on $PLATFORM / $PRESET"
  ARGS=(ai endpoint create --name "$ENDPOINT_NAME" --parent-id "$NEBIUS_PROJECT_ID"
        --image "$IMAGE" --platform "$PLATFORM" --preset "$PRESET"
        --public --container-port 8080 --subnet-id "$NEBIUS_SUBNET_ID"
        --auth "$ENDPOINT_AUTH"
        --env "LATCH_MAX_LIVE_RUNS_PER_DAY=$MAX_RUNS_PER_DAY"
        --format json)
  [ -n "$DISK_SIZE" ] && ARGS+=(--disk-size "$DISK_SIZE")
  [ -n "${GITHUB_TOKEN:-}" ] && ARGS+=(--env "GITHUB_TOKEN=${GITHUB_TOKEN}")
  if [ -n "$SECRET_SELECTOR" ]; then
    ARGS+=(--env-secret "NEBIUS_API_KEY=$SECRET_SELECTOR")        # MysteryBox: the key never appears in the spec
  else
    # NOTE: a plain --env value is stored in the endpoint spec (visible to project admins). Prefer SECRET_SELECTOR.
    ARGS+=(--env "NEBIUS_API_KEY=${NEBIUS_API_KEY}")
  fi
  if [ "$DRY_RUN" = "1" ]; then
    printf 'DRY_RUN: nebius'; printf ' %q' "${ARGS[@]//${NEBIUS_API_KEY:-__none__}/<redacted>}"; printf '\n'
    exit 0
  fi
  ENDPOINT_ID="$(nebius "${ARGS[@]}" | jq -r '.metadata.id // .resource_id // empty')"
  [ -n "$ENDPOINT_ID" ] || die "endpoint create did not return an id; check 'nebius ai endpoint list'"
fi

# ---------------------------------------------------------------- url
say "Waiting for the public HTTPS URL of $ENDPOINT_ID"
URL=""
for _ in $(seq 1 60); do
  URL="$(nebius ai endpoint get "$ENDPOINT_ID" --format json \
    | jq -r '.status.public_endpoints[]? | select(startswith("https://"))' | head -1)"
  [ -n "$URL" ] && break
  sleep 10
done
[ -n "$URL" ] || die "no HTTPS URL yet; check: nebius ai endpoint get $ENDPOINT_ID --format json"
say "Endpoint is up"
echo "$URL"
echo "Health check: curl -s $URL/healthz" >&2
