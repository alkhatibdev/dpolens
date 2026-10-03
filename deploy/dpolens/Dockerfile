# The engine, the HTTP API and the command line, in one image.
#
# The same image runs the one off setup, serves the API, and is where an
# operator runs `dpolens` commands, because all three are the same program with
# the same configuration.
#
# The embedding model is baked in at build time, and the API refuses to serve if
# it is not there.

FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    # The build runs as a user with no home directory, so there is nowhere for a
    # download cache to live, and nothing after the build would read it anyway.
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/dpolens/.venv \
    PATH=/opt/dpolens/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/dpolens/models \
    HOME=/opt/dpolens

# One fixed id in both images, because the credential the API writes is readable
# by its owner alone and the MCP server has to be that owner. The user exists
# before anything is installed: changing the owner of a directory afterwards
# copies every file in it into a new layer, which for a virtual environment and
# a model is most of the image again.
RUN groupadd --gid 10001 dpolens \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin dpolens \
    && mkdir -p /opt/dpolens /run/dpolens \
    && chown dpolens:dpolens /opt/dpolens /run/dpolens

WORKDIR /opt/dpolens
USER dpolens

# Dependencies first, from the lock file, so a change to the source does not
# resolve or download them again.
COPY --chown=dpolens:dpolens pyproject.toml uv.lock ./
COPY --chown=dpolens:dpolens packages/dpolens/pyproject.toml packages/dpolens/
COPY --chown=dpolens:dpolens packages/dpolens-mcp/pyproject.toml packages/dpolens-mcp/
RUN uv sync --frozen --no-dev --package dpolens --no-install-workspace

# Then the model, which is 200 MB and depends on one file: the one that says
# which model this version uses. Copying only that file keeps every later source
# change from fetching it again.
COPY --chown=dpolens:dpolens packages/dpolens/src/dpolens/engine/embedding/models.py \
     packages/dpolens/src/dpolens/engine/embedding/models.py
RUN PYTHONPATH=packages/dpolens/src python -c "\
from dpolens.engine.embedding.models import DEFAULT_MODEL, MODELS; \
from huggingface_hub import hf_hub_download; \
model = MODELS[DEFAULT_MODEL]; \
hf_hub_download(model.repo, 'tokenizer.json'); \
hf_hub_download(model.repo, model.onnx_file)"

# From here on, nothing is allowed to ask the hub about the model it already
# has. Without this, starting a container makes a request to huggingface.co and
# only falls back to the cache when that fails, which is not the same thing as
# running offline. Pass HF_HUB_OFFLINE=0 to fetch a different model by hand.
ENV HF_HUB_OFFLINE=1

COPY --chown=dpolens:dpolens alembic.ini ./
COPY --chown=dpolens:dpolens packages/ packages/
COPY --chown=dpolens:dpolens packs/ packs/
COPY --chmod=755 deploy/dpolens/setup.sh deploy/dpolens/serve.sh /usr/local/bin/
RUN uv sync --frozen --no-dev --package dpolens

EXPOSE 8000
CMD ["serve.sh"]
