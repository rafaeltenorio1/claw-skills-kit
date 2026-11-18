#!/bin/sh
# Configure a fresh (or existing) OpenClaw state inside the container. Safe to run again.
# Needs ANTHROPIC_API_KEY and OPENCLAW_GATEWAY_TOKEN in the environment; both are stored as env references,
# never as values. Prints progress lines only; never prints a secret.
set -eu

KIT=/opt/claw-skills-kit
STATE="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
WORKSPACE="$STATE/workspace"
HOST_PORT="${CSK_HOST_PORT:-18790}"

for name in ANTHROPIC_API_KEY OPENCLAW_GATEWAY_TOKEN; do
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
        echo "bootstrap: $name is not set (check the env file given to docker compose)" >&2
        exit 1
    fi
done
unset value

step() { echo "bootstrap: $*"; }

# 1. First run only: non-interactive onboarding, secrets stored as env references.
if [ ! -f "$STATE/openclaw.json" ]; then
    step "onboarding (secrets as env references)"
    openclaw onboard --non-interactive --accept-risk --skip-health --mode local \
        --auth-choice apiKey --secret-input-mode ref \
        --gateway-auth token --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
        --gateway-bind lan --gateway-port 18789 \
        --skip-channels --skip-daemon --skip-search --skip-skills --skip-ui --skip-hooks
else
    step "existing config found, onboarding skipped"
fi

# 2. The settings chosen during the project (see CLAUDE.md / docs/decisions.md).
step "applying settings"
openclaw config set --batch-json "[
  {\"path\": \"agents.defaults.model.primary\", \"value\": \"anthropic/claude-opus-5-5\"},
  {\"path\": \"agents.defaults.heartbeat.every\", \"value\": \"0m\"},
  {\"path\": \"skills.entries.skill-creator.enabled\", \"value\": false},
  {\"path\": \"plugins.entries.memory-core.config.dreaming.enabled\", \"value\": false},
  {\"path\": \"gateway.controlUi.allowedOrigins\",
   \"value\": [\"http://127.0.0.1:$HOST_PORT\", \"http://localhost:$HOST_PORT\"]}
]"

# 2b. Browser images only: Chrome's own sandbox cannot start in a container (it aborts with signal 6),
#     so it is turned off; the container is the isolation boundary. Images without Chromium are left alone.
if ls -d "$HOME"/.cache/ms-playwright/chromium-* > /dev/null 2>&1; then
    step "browser found: turning off Chrome's in-container sandbox"
    openclaw config set browser.noSandbox true
fi

# 3. The skill-manager skill, replaced by the copy baked into the image.
step "installing skill-manager"
mkdir -p "$WORKSPACE/skills"
rm -rf "$WORKSPACE/skills/skill-manager"
cp -r "$KIT/skill-manager" "$WORKSPACE/skills/skill-manager"

# 3b. First run only: this host's descriptor (one client per gateway) and the golden skills at the OLDEST release,
#     installed by the reconciler itself. Later runs leave both alone, so an update made in chat is never undone.
if [ ! -f "$CSK_HOST" ]; then
    first="${CSK_INITIAL_RELEASE:-$(ls "$CSK_RELEASES" | sort | head -n 1)}"
    step "first run: writing the host descriptor and installing release $first"
    mkdir -p "$(dirname "$CSK_HOST")"
    "$CSK_PYTHON" - "$CSK_HOST" "$WORKSPACE/skills" "$CSK_RELEASES/$first/skills.lock.json" <<'EOF'
import json, os, sys
out, skills_dir, lock = sys.argv[1:4]
with open(lock, encoding="utf-8") as f:
    skills = sorted(json.load(f)["skills"])
descriptor = {
    "host_id": os.environ.get("CSK_HOST_ID", "csk-demo"),
    "skills_dir": skills_dir,
    "clients": [os.environ.get("CSK_CLIENT_ID", "demo-client")],
    "skills": skills,
    "smoke": {"timeout_seconds": 120, "commands": [
        ["openclaw", "config", "validate"],
        ["openclaw", "skills", "list"],
    ]},
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(descriptor, f, indent=2)
    f.write("\n")
EOF
    "$CSK_PYTHON" -m claw_skills_kit reconcile --host "$CSK_HOST" \
        --library "$CSK_RELEASES/$first/skills" --target "$WORKSPACE/skills" \
        --pins "$CSK_RELEASES/$first/skills.lock.json" --apply
else
    step "host descriptor found, golden skills left as they are"
fi

# 4. operator rules at the top of the workspace AGENTS.md.
step "applying operator rules to AGENTS.md"
[ -f "$WORKSPACE/AGENTS.md" ] || : > "$WORKSPACE/AGENTS.md"
"$CSK_PYTHON" "$KIT/apply_agents_rules.py" "$KIT/AGENTS.csk.md" "$WORKSPACE/AGENTS.md"

# 5. Checks (exit codes only).
step "checking config"
openclaw config validate
step "checking secrets"
openclaw secrets audit --check
step "done"
