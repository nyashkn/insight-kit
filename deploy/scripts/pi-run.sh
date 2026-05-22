#!/usr/bin/env bash
#
# pi-run.sh — launch the `pi` coding agent with provider credentials injected
# from Infisical at process start. No credential is ever written to disk, git,
# or this script; `infisical run` injects them into pi's environment only.
#
# pi reads provider keys from the environment
# (pi-ai: getApiKeyEnvVars in dist/env-api-keys.js):
#
#   opencode-go  -> OPENCODE_API_KEY
#   openrouter   -> OPENROUTER_API_KEY
#   anthropic    -> ANTHROPIC_OAUTH_TOKEN   (Claude Pro/Max subscription auth;
#                                            takes precedence over ANTHROPIC_API_KEY)
#
# All of these live in ONE Infisical project (PI_CREDS_PROJECT) under PI_CREDS_ENV.
# `infisical run` injects EVERY secret in that project/env into pi's environment.
#
# The Claude Pro/Max token is stored in Infisical as CLAUDE_CODE_OAUTH_TOKEN (it
# is a Claude Code OAuth token); pi does NOT read that name — it reads
# ANTHROPIC_OAUTH_TOKEN. The launch step below aliases CLAUDE_CODE_OAUTH_TOKEN ->
# ANTHROPIC_OAUTH_TOKEN just before exec'ing pi. A directly-set
# ANTHROPIC_OAUTH_TOKEN (from the caller or Infisical) always wins.
#
# Auth to Infisical itself:
#   * Container / self-improvement loop: set INFISICAL_CLIENT_ID and
#     INFISICAL_CLIENT_SECRET — a scoped, read-only Universal-Auth Machine
#     Identity. The wrapper exchanges them for a short-lived token.
#   * Local dev: run `infisical login --domain=$INFISICAL_DOMAIN` once; the
#     wrapper reuses that session.
#
# Usage:  bash scripts/pi-run.sh [pi args...]       (or: bun run pi -- [pi args])
#
set -euo pipefail

INFISICAL_DOMAIN="${INFISICAL_DOMAIN:-https://infisical.lan.ds.ke}"
# Provider-credentials project on the self-hosted Infisical (kn-personal-dev) —
# holds OPENCODE_API_KEY, OPENROUTER_API_KEY, CLAUDE_CODE_OAUTH_TOKEN.
PI_CREDS_PROJECT="${PI_CREDS_PROJECT:-fe4ca4e9-9dc4-491f-a8ef-61dae117b0ff}"
PI_CREDS_ENV="${PI_CREDS_ENV:-prod}"

for bin in infisical pi; do
	command -v "$bin" >/dev/null 2>&1 || {
		echo "pi-run: '$bin' not found on PATH." >&2
		exit 127
	}
done

if [[ -z "${INSIGHT_KIT_RUN_DIR:-}" ]]; then
	echo "pi-run: note — INSIGHT_KIT_RUN_DIR is unset; the L1 gate emit tools" >&2
	echo "        (ik_*_emit) stay blocked until it points at a run directory." >&2
fi

if [[ -n "${INFISICAL_CLIENT_ID:-}" && -n "${INFISICAL_CLIENT_SECRET:-}" ]]; then
	# Machine-identity path — exchange Universal-Auth client creds for a
	# short-lived token. NOTE: --client-secret on argv is briefly visible to
	# `ps` on a shared host; acceptable for a single-tenant container, and the
	# token is short-lived. Harden by switching to Infisical's native
	# INFISICAL_UNIVERSAL_AUTH_* env auth if the host is multi-tenant.
	token="$(infisical login --method=universal-auth \
		--client-id="$INFISICAL_CLIENT_ID" \
		--client-secret="$INFISICAL_CLIENT_SECRET" \
		--domain="$INFISICAL_DOMAIN" --plain --silent 2>/dev/null || true)"
	if [[ -z "$token" ]]; then
		echo "pi-run: Infisical machine-identity login failed." >&2
		exit 1
	fi
	export INFISICAL_TOKEN="$token"
fi

# `infisical run` injects the project secrets; the inner shell aliases the
# Claude token to the name pi expects, then exec's pi. The alias expression is
# literal in argv — no token value is ever placed on a command line.
# shellcheck disable=SC2016  # the bash -c body MUST stay single-quoted — it is
# evaluated by the INNER shell, after `infisical run` has injected the secrets.
exec infisical run \
	--projectId="$PI_CREDS_PROJECT" \
	--env="$PI_CREDS_ENV" \
	--domain="$INFISICAL_DOMAIN" \
	-- bash -c 'export ANTHROPIC_OAUTH_TOKEN="${ANTHROPIC_OAUTH_TOKEN:-${CLAUDE_CODE_OAUTH_TOKEN:-}}"; exec pi "$@"' pi-run "$@"
