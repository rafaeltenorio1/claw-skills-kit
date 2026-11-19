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

COPY skills/skill-manager /opt/claw-skills-kit/skill-manager
# The golden skill library, one folder per release with its pins. Owned by root: the agent can read, not edit.
COPY library /opt/claw-skills-kit/library
# Rollback demo, off by default: CSK_DEMO_ROLLBACK=1 adds the releases in library/demo-releases (broken on
# purpose) to the library the agent sees. docker/up.sh passes it through.
ARG CSK_DEMO_ROLLBACK=0
RUN if [ "$CSK_DEMO_ROLLBACK" = "1" ]; then \
        cp -r /opt/claw-skills-kit/library/demo-releases/. /opt/claw-skills-kit/library/releases/; \
    fi
COPY host/AGENTS.csk.md /opt/claw-skills-kit/AGENTS.csk.md
COPY docker/bootstrap.sh docker/apply_agents_rules.py /opt/claw-skills-kit/
RUN chmod 0755 /opt/claw-skills-kit/bootstrap.sh /opt/claw-skills-kit/skill-manager/scripts/lk

# skill-manager's `lk` uses this interpreter when it is set (no repository checkout in the container).
ENV CSK_PYTHON=/opt/claw-skills-kit/venv/bin/python \
    CSK_RELEASES=/opt/claw-skills-kit/library/releases \
    CSK_HOST=/home/node/.openclaw/csk/host.json
USER node
