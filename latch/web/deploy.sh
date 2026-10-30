#!/usr/bin/env bash
# Deploy Latch web to Nebius Serverless AI (container registry + HTTPS endpoint).
#
#   NEBIUS_PROJECT_ID=project-... NEBIUS_SUBNET_ID=vpcsubnet-... [NEBIUS_REGION=eu-north1] \
#   latch/web/deploy.sh [deploy|build|vercel]
#
# Secrets (never printed, never written to a file, never baked into the image):
#   NEBIUS_API_KEY  from the environment, else the `export NEBIUS_API_KEY=...` line of ~/.zshrc
#                   (parsed, not sourced).
#   GITHUB_TOKEN    from the environment, else read at deploy time from
#                   $GITHUB_ACCOUNT_FILE (default ~/.config/github/account.json), key
#                   $GITHUB_TOKEN_ACCOUNT (default "aarav"), field "token"  ({"aarav": {"token": ...}}).
# Both are stored in ONE MysteryBox secret (payload keys NEBIUS_API_KEY / GITHUB_TOKEN) and injected into
# the endpoint with `--env-secret KEY=<secret id>`, so neither value appears in the endpoint spec.
#
# This script NEVER logs you in. Run `nebius profile create` yourself first.
# Nothing here has been run by the author: read it, then run it deliberately.
# DRY_RUN=1 prints every mutating command (secrets shown as ***) and needs no Nebius login.
set -euo pipefail

CMD="${1:-deploy}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

: "${NEBIUS_REGION:=eu-north1}"                 # region of the project (cr.<region>.nebius.cloud)
: "${REGISTRY_NAME:=latch}"
: "${IMAGE_NAME:=latch-web}"
: "${ENDPOINT_NAME:=latch-web}"
: "${PLATFORM:=cpu-d3}"
: "${PRESET:=4vcpu-16gb}"
: "${DISK_SIZE:=50Gi}"                          # the CLI default is 250Gi; this app needs far less
: "${ENDPOINT_AUTH:=none}"                      # none = reachable by judges without a token; token = private
: "${UPDATE_MODE:=recreate}"                    # recreate (delete + create, new tag) | restart (same tag re-pushed)
: "${MAX_RUNS_PER_DAY:=50}"                     # LATCH_MAX_LIVE_RUNS_PER_DAY
: "${SECRET_NAME:=${ENDPOINT_NAME}-env}"          # MysteryBox secret holding NEBIUS_API_KEY (+ GITHUB_TOKEN)
: "${GITHUB_TOKEN_ACCOUNT:=aarav}"              # key in the account file; never use another person's account
: "${GITHUB_ACCOUNT_FILE:=$HOME/.config/github/account.json}"
: "${PUBLIC_IP:=0}"                            # 1 = also assign a public IP (not needed: the managed https:// URL is always provided)
: "${DRY_RUN:=0}"
: "${IMAGE_TAG:=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"

say() { printf '\n==> %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'warning: %s\n' "$*" >&2; }

# Every secret value we hold is registered here so that nothing we print can contain it.
SECRETS=()
register_secret() { [ -z "${1:-}" ] || SECRETS+=("$1"); }
mask() {
  local a="$1" v
  for v in ${SECRETS[@]+"${SECRETS[@]}"}; do a="${a//"$v"/***}"; done
  printf '%s' "$a"
}
show() {   # print a command with secrets masked
  local a m
  for a in "$@"; do
    m="$(mask "$a")"
    case "$m" in *'***'*) printf " '%s'" "$m" ;; *) printf ' %q' "$m" ;; esac
  done
  printf '\n'
}
run() {
  if [ "$DRY_RUN" = "1" ]; then printf 'DRY_RUN:'; show "$@"; else "$@"; fi
}
need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  if [ "$DRY_RUN" = "1" ]; then warn "$1 is not on PATH (continuing, dry run)"; else die "$1 is required but not on PATH"; fi
}
[ -d "$HOME/.nebius/bin" ] && PATH="$HOME/.nebius/bin:$PATH"

# ---------------------------------------------------------------- secret loading (values are never printed)
PY_ZSHRC='import re, sys
val = ""
for line in open(sys.argv[1], errors="ignore"):
    m = re.match(r"\s*(?:export\s+)?NEBIUS_API_KEY=(.*)$", line.rstrip("\n"))
    if not m:
        continue
    v = m.group(1).strip()
    if len(v) >= 2 and v[0] in "\"\x27" and v[-1] == v[0]:
        v = v[1:-1]
    else:
        v = re.split(r"\s+#", v)[0].strip()
    if v and not re.search(r"\$\(|\$\{|`", v):
        val = v
sys.stdout.write(val)'
PY_GHTOKEN='import json, os, sys
d = json.load(open(os.path.expanduser(sys.argv[1])))
sys.stdout.write(str(d[sys.argv[2]]["token"]))'
PY_PAYLOAD='import json, os
print(json.dumps([{"key": k, "string_value": os.environ["P_" + k]}
                  for k in ("NEBIUS_API_KEY", "GITHUB_TOKEN") if os.environ.get("P_" + k)]))'

load_nebius_key() {
  [ -z "${NEBIUS_API_KEY:-}" ] || return 0
  local zrc="${ZSHRC_FILE:-$HOME/.zshrc}"
  [ -r "$zrc" ] || return 0
  NEBIUS_API_KEY="$(python3 -c "$PY_ZSHRC" "$zrc" 2>/dev/null || true)"
}
load_github_token() {
  [ -z "${GITHUB_TOKEN:-}" ] || return 0
  [ "$GITHUB_TOKEN_ACCOUNT" != "kamalbuilds" ] || die "GITHUB_TOKEN_ACCOUNT=kamalbuilds is not allowed for this deploy"
  [ -r "$GITHUB_ACCOUNT_FILE" ] || { warn "no GITHUB_TOKEN and $GITHUB_ACCOUNT_FILE is unreadable: the app will use GitHub's anonymous 60/h limit"; return 0; }
  GITHUB_TOKEN="$(python3 -c "$PY_GHTOKEN" "$GITHUB_ACCOUNT_FILE" "$GITHUB_TOKEN_ACCOUNT" 2>/dev/null || true)"
  [ -n "$GITHUB_TOKEN" ] || warn "no \"$GITHUB_TOKEN_ACCOUNT\".token in $GITHUB_ACCOUNT_FILE: the app will use GitHub's anonymous 60/h limit"
}


# ---------------------------------------------------------------- vercel fallback
deploy_vercel() {
  # VERCEL_CLI=vca runs as the vca profile that owns the repo (vca use aarav); bare `vercel` uses whatever login is the default
  local cli="${VERCEL_CLI:-vca}"; need "$cli"
  [ "$cli" != vca ] || say "Vercel profile: $(vca current)"
  local stage; stage="$(mktemp -d)/latch"; mkdir -p "$stage"   # the directory name becomes the Vercel project name
  say "Staging a cached-receipts-only Vercel project in $stage"
  mkdir -p "$stage/latch"
  (cd "$REPO_ROOT" && shopt -s nullglob && tar --exclude='__pycache__' --exclude='.data' --exclude='test_*.py' \
      -cf - latch/*.py latch/harness/*.py latch/web latch/runs/click-3298.json latch/runs/loop-demo-events.jsonl \
      latch/runs/eval-summary*.json latch/runs/eval-diff*.json latch/runs/eval latch/runs/eval-repair*/) \
    | tar -xf - -C "$stage"
  mkdir -p "$stage/api"
  cp "$REPO_ROOT/latch/web/vercel/api/index.py" "$stage/api/index.py"
  # explicit build: zero-config detection skipped api/index.py (empty build, every route 404); includeFiles bundles the receipts and static
  printf '%s\n' '{ "builds": [ { "src": "api/index.py", "use": "@vercel/python", "config": { "includeFiles": "latch/**" } } ],' \
    '  "routes": [ { "src": "/(.*)", "dest": "/api/index.py" } ] }' > "$stage/vercel.json"
  say "Deploying (live runs are off on Vercel; the UI shows the cached receipts)"
  (cd "$stage" && run "$cli" deploy --prod --yes)
}

if [ "$CMD" = "vercel" ]; then deploy_vercel; exit 0; fi
[ "$CMD" = "deploy" ] || [ "$CMD" = "build" ] || die "usage: deploy.sh [deploy|build|vercel]"

# ---------------------------------------------------------------- preflight
need docker; need nebius; need jq; need python3
if [ "$DRY_RUN" = "1" ]; then
  : "${NEBIUS_PROJECT_ID:=project-DRYRUN}"; : "${NEBIUS_SUBNET_ID:=vpcsubnet-DRYRUN}"
  say "DRY_RUN: no Nebius calls are made and no login is needed (placeholders used for unset ids)"
fi
: "${NEBIUS_PROJECT_ID:?set NEBIUS_PROJECT_ID (the project that will own the registry and endpoint)}"
if [ "$CMD" = "deploy" ]; then
  : "${NEBIUS_SUBNET_ID:?set NEBIUS_SUBNET_ID (nebius vpc subnet list)}"
  load_nebius_key
  load_github_token
  if [ -z "${NEBIUS_API_KEY:-}" ]; then
    if [ "$DRY_RUN" = "1" ]; then warn "NEBIUS_API_KEY not found (env or ~/.zshrc); using a placeholder"; NEBIUS_API_KEY="DRYRUN-PLACEHOLDER"
    else die "NEBIUS_API_KEY not found: export it, or add an 'export NEBIUS_API_KEY=...' line to ~/.zshrc"; fi
  fi
  register_secret "$NEBIUS_API_KEY"; register_secret "${GITHUB_TOKEN:-}"
  say "Secrets: NEBIUS_API_KEY loaded; GITHUB_TOKEN $([ -n "${GITHUB_TOKEN:-}" ] && echo loaded || echo absent) (values are never printed)"
fi
if [ "$DRY_RUN" != "1" ] && ! nebius iam whoami >/dev/null 2>&1; then
  die "the Nebius CLI is not logged in. Run 'nebius profile create' yourself, then re-run this script."
fi

# ---------------------------------------------------------------- registry
say "Looking for container registry '$REGISTRY_NAME' in $NEBIUS_PROJECT_ID"
REGISTRY_ID=""
if [ "$DRY_RUN" != "1" ]; then
  REGISTRY_ID="$(nebius registry list --parent-id "$NEBIUS_PROJECT_ID" --format json \
    | jq -r --arg n "$REGISTRY_NAME" '.items // [] | map(select(.metadata.name == $n)) | .[0].metadata.id // empty')"
fi
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
EXISTING_ID=""
if [ "$DRY_RUN" != "1" ]; then
  EXISTING_ID="$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" --parent-id "$NEBIUS_PROJECT_ID" --format json 2>/dev/null \
    | jq -r '.metadata.id // empty' || true)"
fi

# Secrets go into a MysteryBox secret whose payload keys equal the env var names; the endpoint then
# references it with --env-secret KEY=<secret id> (the CLI reads the payload entry whose key == KEY).
# The JSON payload is passed to the CLI as one argument (briefly visible to `ps` for this user on this
# machine only); it is never written to a file and never printed unmasked.
ensure_secret() {
  local payload sid=""
  payload="$(P_NEBIUS_API_KEY="$NEBIUS_API_KEY" P_GITHUB_TOKEN="${GITHUB_TOKEN:-}" python3 -c "$PY_PAYLOAD")"
  if [ "$DRY_RUN" != "1" ]; then
    sid="$(nebius mysterybox secret get-by-name --name "$SECRET_NAME" --parent-id "$NEBIUS_PROJECT_ID" --format json 2>/dev/null \
      | jq -r '.metadata.id // empty' || true)"
  fi
  if [ -n "$sid" ]; then
    say "Adding a new version to MysteryBox secret '$SECRET_NAME' ($sid)"
    run nebius mysterybox secret-version create --parent-id "$sid" --payload "$payload" \
      --description "latch-web $IMAGE_TAG" --set-primary --format json >/dev/null
  else
    say "Creating MysteryBox secret '$SECRET_NAME'"
    if [ "$DRY_RUN" = "1" ]; then
      run nebius mysterybox secret create --name "$SECRET_NAME" --parent-id "$NEBIUS_PROJECT_ID" \
        --secret-version-payload "$payload" --secret-version-set-primary --format json
      sid="mbsec-DRYRUN"
    else
      sid="$(nebius mysterybox secret create --name "$SECRET_NAME" --parent-id "$NEBIUS_PROJECT_ID" \
        --secret-version-payload "$payload" --secret-version-set-primary --format json \
        | jq -r '.metadata.id // .resource_id // empty')"
      [ -n "$sid" ] || die "mysterybox secret create did not return an id; check 'nebius mysterybox secret list --parent-id $NEBIUS_PROJECT_ID'"
    fi
  fi
  SECRET_ID="$sid"
}

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
  ensure_secret
  say "Creating endpoint '$ENDPOINT_NAME' on $PLATFORM / $PRESET (auth: $ENDPOINT_AUTH)"
  ARGS=(ai endpoint create --name "$ENDPOINT_NAME" --parent-id "$NEBIUS_PROJECT_ID"
        --image "$IMAGE" --platform "$PLATFORM" --preset "$PRESET"
        --container-port 8080 --subnet-id "$NEBIUS_SUBNET_ID"
        --auth "$ENDPOINT_AUTH"
        --env "LATCH_MAX_LIVE_RUNS_PER_DAY=$MAX_RUNS_PER_DAY"
        --env-secret "NEBIUS_API_KEY=$SECRET_ID"
        --format json)
  [ -z "${GITHUB_TOKEN:-}" ] || ARGS+=(--env-secret "GITHUB_TOKEN=$SECRET_ID")
  [ -z "$DISK_SIZE" ] || ARGS+=(--disk-size "$DISK_SIZE")
  [ "$PUBLIC_IP" != "1" ] || ARGS+=(--public)
  if [ "$DRY_RUN" = "1" ]; then
    printf 'DRY_RUN: nebius'; show "${ARGS[@]}"
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
