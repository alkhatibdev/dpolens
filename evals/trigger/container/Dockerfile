# Where one trigger run happens: Claude Code at a pinned version, as an
# ordinary user, in a checkout of the Larder app with its dependencies
# installed, the way a developer's machine would have it.
#
# Built by scripts/run_trigger_test.py with evals/trigger as the context.

FROM node:24-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.288

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates git openssl; \
    rm -rf /var/lib/apt/lists/*; \
    npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; \
    claude --version

COPY --chmod=755 container/prepare-profile.sh container/run-task.sh /usr/local/bin/

# The pinned version is the one measured, so nothing may update it mid-batch.
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CONFIG_DIR=/home/node/.claude

USER node
WORKDIR /home/node/larder

# A named volume mounted here starts out owned by this user, which is how the
# prepared profile reaches every run read-only.
RUN mkdir -p /home/node/.claude /home/node/profile

COPY --chown=node:node app/ ./

RUN set -eux; \
    npm ci --no-audit --no-fund; \
    cp .env.example .env; \
    npx prisma migrate deploy; \
    npx prisma generate; \
    npm run typecheck

# A short history, because a real checkout has one and Claude Code reads it.
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
