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

# Alpaca's official Trading CLI (github.com/alpacahq/cli): a single static Go
# binary. With OA_BROKER_TRANSPORT=cli the broker adapter routes every
# account / position / order / clock call through it (hackathon requirement:
# Trading API via MCP or CLI). Pinned + checksum-verified so a tampered or
# moved release fails the build instead of shipping.
ARG ALPACA_CLI_VERSION=0.0.14
ARG ALPACA_CLI_SHA256=6c82ef31f94dd61aae1c90e40fc41fdfaf8111bd50e9a2780b9d8d304eb2ba66
RUN set -eux; \
    curl -fsSL -o /tmp/alpaca-cli.tgz \
      "https://github.com/alpacahq/cli/releases/download/v${ALPACA_CLI_VERSION}/cli_${ALPACA_CLI_VERSION}_linux_amd64.tar.gz"; \
    echo "${ALPACA_CLI_SHA256}  /tmp/alpaca-cli.tgz" | sha256sum -c -; \
    tar -xzf /tmp/alpaca-cli.tgz -C /tmp alpaca; \
    install -m 0755 /tmp/alpaca /usr/local/bin/alpaca; \
    rm -f /tmp/alpaca-cli.tgz /tmp/alpaca; \
    /usr/local/bin/alpaca version

# Mirror the Mac path for consistency with the sibling bots' containers.
WORKDIR /Users/mo/OptionsAgent

# Python deps first (layer cache: only re-runs when requirements.txt changes).
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh cron/*.sh \
    && sed -i 's/\r$//' entrypoint.sh cron/*.sh 2>/dev/null || true

ENTRYPOINT ["/Users/mo/OptionsAgent/entrypoint.sh"]
