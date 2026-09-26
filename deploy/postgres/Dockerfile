# PostgreSQL for DPOLens: pgvector for meaning, pg_textsearch for BM25.
#
# Both halves of retrieval live in one database. pg_textsearch has to be in
# shared_preload_libraries, which is why this is an image rather than a
# CREATE EXTENSION at startup.

FROM pgvector/pgvector:pg17

ARG PG_TEXTSEARCH_VERSION=1.4.0

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl unzip; \
    # Read the architecture from dpkg rather than TARGETARCH, which only
    # BuildKit provides: the test suite builds this image through docker-py,
    # which uses the legacy builder.
    arch="$(dpkg --print-architecture)"; \
    curl -fsSL -o /tmp/pg_textsearch.zip \
      "https://github.com/timescale/pg_textsearch/releases/download/v${PG_TEXTSEARCH_VERSION}/pg-textsearch-v${PG_TEXTSEARCH_VERSION}-pg17-${arch}.zip"; \
    unzip -o /tmp/pg_textsearch.zip -d /tmp/pg_textsearch; \
    # The archive holds a Debian package, not loose files.
    dpkg -i /tmp/pg_textsearch/*.deb; \
    test -f "$(pg_config --pkglibdir)/pg_textsearch.so"; \
    test -f "$(pg_config --sharedir)/extension/pg_textsearch.control"; \
    rm -rf /tmp/pg_textsearch /tmp/pg_textsearch.zip; \
    apt-get purge -y --auto-remove curl unzip; \
    rm -rf /var/lib/apt/lists/*

# The extension registers its index access method at load time, so it has to be
# preloaded before any database exists.
RUN printf "shared_preload_libraries = 'pg_textsearch'\n" \
      > /usr/share/postgresql/postgresql.conf.sample.dpolens; \
    cat /usr/share/postgresql/postgresql.conf.sample.dpolens \
      >> /usr/share/postgresql/postgresql.conf.sample; \
    rm /usr/share/postgresql/postgresql.conf.sample.dpolens
