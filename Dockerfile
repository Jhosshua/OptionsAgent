# OptionsAgent on Railway.
#
# Mirrors the proven DeterministicAgent-Railway pattern: real Linux cron with
# an ET-timezone container, scripts that self-gate by Eastern time AND the
# broker market clock, state on a Railway volume mounted at data/.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/New_York

RUN apt-get update && apt-get install -y --no-install-recommends \
        cron bash tzdata procps coreutils ca-certificates curl gnupg \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# harness/proposer.py shells out to the Claude Code CLI and FAILS CLOSED (no
# trade) when it is missing, so the container must carry it or the bot deploys
# green and silently never trades. Auth is headless via CLAUDE_CODE_OAUTH_TOKEN,
# injected by entrypoint.sh; OA_CLAUDE_CLI must point at the path below.
# npm installs its own `claude` bin shim; do NOT hand-symlink cli.js (the package
# layout moved, and a dangling link silently disarms the proposer). The
# command -v + --version below assert the executable really runs, so a broken
# install fails the BUILD rather than a trading day.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && command -v claude \
    && claude --version \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# Mirror the Mac path for consistency with the sibling bots' containers.
WORKDIR /Users/mo/OptionsAgent

# Python deps first (layer cache: only re-runs when requirements.txt changes).
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh cron/*.sh \
    && sed -i 's/\r$//' entrypoint.sh cron/*.sh 2>/dev/null || true

ENTRYPOINT ["/Users/mo/OptionsAgent/entrypoint.sh"]
