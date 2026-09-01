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

# The AI proposer (harness/proposer.py) calls the DeepSeek HTTP API with
# DEEPSEEK_API_KEY since 2026-09-01. The container deliberately does NOT carry
# the Claude Code CLI any more: the CLI login expired twice ("Not logged in ·
# Please run /login") and each time the once-a-day entry cycle failed closed
# and the whole trading day was lost. An API key has no login to lose.
# Set OA_LLM_PROVIDER=claude_cli only on the Mac, where the CLI exists.

# Mirror the Mac path for consistency with the sibling bots' containers.
WORKDIR /Users/mo/OptionsAgent

# Python deps first (layer cache: only re-runs when requirements.txt changes).
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh cron/*.sh \
    && sed -i 's/\r$//' entrypoint.sh cron/*.sh 2>/dev/null || true

ENTRYPOINT ["/Users/mo/OptionsAgent/entrypoint.sh"]
