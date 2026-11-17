# Where one trigger run happens: an AI coding assistant at a pinned version, as
# an ordinary user, in a checkout of the Larder app with its dependencies
# installed, the way a developer's machine would have it.
#
# Built by scripts/run_trigger_test.py with evals/trigger as the context, one
# target for each AI assistant: claude-code or qwen-code. Both start from the
# same checkout.

FROM node:24-bookworm-slim AS larder

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates git openssl; \
    rm -rf /var/lib/apt/lists/*

USER node
WORKDIR /home/node/larder

# A named volume mounted here starts out owned by this user, which is how the
# prepared profile reaches every run read-only.
RUN mkdir -p /home/node/profile

COPY --chown=node:node app/ ./

RUN set -eux; \
    npm ci --no-audit --no-fund; \
    cp .env.example .env; \
    npx prisma migrate deploy; \
    npx prisma generate; \
    npm run typecheck

# A short history, because a real checkout has one and the AI assistant reads it.
RUN set -eux; \
    git init -q -b main; \
    git config user.name "Sam Okafor"; \
    git config user.email "sam@larder.shop"; \
    commit() { \
      GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git commit -q -m "$2"; \
    }; \
    git add package.json package-lock.json tsconfig.json .gitignore .env.example README.md \
      prisma src/app.ts src/server.ts src/config.ts src/db.ts src/lib/logger.ts \
      src/lib/money.ts src/middleware/errors.ts src/middleware/requestLogger.ts \
      src/routes/products.ts public test; \
    commit "2026-07-14T09:30:00Z" "Product catalogue and front page"; \
    git add src/middleware/auth.ts src/routes/auth.ts src/routes/account.ts \
      src/services/users.ts src/lib/mailer.ts; \
    commit "2026-08-02T16:05:00Z" "Accounts, sessions and the welcome email"; \
    git add -A; \
    commit "2026-09-19T11:42:00Z" "Orders, with order_placed sent to Segment"; \
    test -z "$(git status --porcelain)"

FROM larder AS claude-code

ARG CLAUDE_CODE_VERSION=2.1.288

USER root
RUN set -eux; \
    npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; \
    claude --version

COPY --chmod=755 container/claude-code/ /usr/local/bin/

# The pinned version is the one measured, so nothing may update it mid-batch.
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CONFIG_DIR=/home/node/.claude

USER node
RUN mkdir -p /home/node/.claude

FROM larder AS qwen-code

ARG QWEN_CODE_VERSION=0.27.4

USER root
RUN set -eux; \
    npm install -g "@qwen-code/qwen-code@${QWEN_CODE_VERSION}"; \
    qwen --version

COPY --chmod=755 container/qwen-code/ /usr/local/bin/

# Every run approves every tool call, so the notice saying so would only repeat
# itself in each transcript. The pinned version is the one measured: the
# settings each run starts from keep it from updating itself.
ENV QWEN_CODE_SUPPRESS_YOLO_WARNING=1

USER node
RUN mkdir -p /home/node/.qwen
