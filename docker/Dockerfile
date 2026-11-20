# OpenClaw gateway with claw-skills-kit and the skill-manager skill baked in.
# Build from the repository root:  docker build -f docker/Dockerfile -t csk-openclaw:local .
# OPENCLAW_BASE picks the official image. Default: the "-browser" tag (Chromium + Xvfb, ~4.6 GB built);
# ghcr.io/openclaw/openclaw:2026.11.3 is the same release without a browser (~3.2 GB built).
ARG OPENCLAW_BASE=ghcr.io/openclaw/openclaw:2026.11.3-browser
FROM ${OPENCLAW_BASE}

# The image ships Python 3.11; claw-skills-kit needs >= 3.12. uv installs its own Python next to the kit,
# so the image's Python is left alone.
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

USER root
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_NO_CACHE=1
COPY pyproject.toml README.md /opt/claw-skills-kit/pkg/
COPY src /opt/claw-skills-kit/pkg/src
RUN uv venv /opt/claw-skills-kit/venv --python 3.14 \
 && uv pip install --python /opt/claw-skills-kit/venv/bin/python /opt/claw-skills-kit/pkg \
 && /opt/claw-skills-kit/venv/bin/python -m claw_skills_kit --help > /dev/null

# Himalaya, the mail CLI behind OpenClaw's bundled `himalaya` skill. Pinned to 1.2.0 because the 2.x series no longer
# reads the config format that skill documents. The download must match its published sha256 or the build fails.
ARG HIMALAYA_VERSION=1.2.0
ARG HIMALAYA_SHA256=e04e6382e3e664ef34b01afa1a2216113194a2975d2859727647b22d9b36d4e4
RUN /opt/claw-skills-kit/venv/bin/python -c "import hashlib, io, sys, tarfile, urllib.request; \
url = 'https://github.com/pimalaya/himalaya/releases/download/v${HIMALAYA_VERSION}/himalaya.x86_64-linux.tgz'; \
data = urllib.request.urlopen(url, timeout=120).read(); \
sys.exit('himalaya sha256 mismatch') if hashlib.sha256(data).hexdigest() != '${HIMALAYA_SHA256}' else None; \
open('/usr/local/bin/himalaya', 'wb').write(tarfile.open(fileobj=io.BytesIO(data)).extractfile('himalaya').read())" \
 && chmod 0755 /usr/local/bin/himalaya && himalaya --version

COPY skills/skill-manager /opt/claw-skills-kit/skill-manager
# The library skill library, one folder per release with its pins. Owned by root: the agent can read, not edit.
COPY library /opt/claw-skills-kit/library
# Rollback demo, off by default: CSK_DEMO_ROLLBACK=1 adds the releases in library/demo-releases (broken on
# purpose) to the library the agent sees. docker/up.sh passes it through.
ARG CSK_DEMO_ROLLBACK=0
RUN if [ "$CSK_DEMO_ROLLBACK" = "1" ]; then \
        cp -r /opt/claw-skills-kit/library/demo-releases/. /opt/claw-skills-kit/library/releases/; \
    fi
COPY host/AGENTS.csk.md /opt/claw-skills-kit/AGENTS.csk.md
COPY docker/bootstrap.sh docker/apply_agents_rules.py /opt/claw-skills-kit/
RUN chmod 0755 /opt/claw-skills-kit/bootstrap.sh /opt/claw-skills-kit/skill-manager/scripts/csk

# skill-manager's `csk` uses this interpreter when it is set (no repository checkout in the container).
ENV CSK_PYTHON=/opt/claw-skills-kit/venv/bin/python \
    CSK_RELEASES=/opt/claw-skills-kit/library/releases \
    CSK_HOST=/home/node/.openclaw/csk/host.json \
    CSK_EVIDENCE=/home/node/.openclaw/csk/evidence.jsonl \
    CSK_BACKUPS=/home/node/.openclaw/csk/backups \
    HIMALAYA_CONFIG=/home/node/.openclaw/csk/himalaya.toml
USER node
