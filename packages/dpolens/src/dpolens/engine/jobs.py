"""Work that runs in the worker rather than in a request.

Two kinds: embedding a version once it is published, so that searching by meaning finds its
clauses, and the daily purge that keeps the retention promise: expired questions, ended
sessions, used-up sign-in links, and original files no version points at. Jobs are kept in
Postgres by Procrastinate, so an instance gains no datastore.

The purge also runs whenever the worker starts. A schedule missed by more than a few minutes is
skipped, so without that an instance that is never running at 03:17 UTC, such as one on a
laptop, would never delete what it promised to.

A job is queued on the connection of the change that needs it, so a change that rolls back
leaves no job behind, and its status is read the same way, synchronously, by any request.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from procrastinate import App, PsycopgConnector, RetryStrategy, SyncPsycopgConnector
from procrastinate.exceptions import NoResult
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from dpolens.engine.auth.links import purge_expired_links
from dpolens.engine.auth.sessions import lifetimes_of, purge_ended
from dpolens.engine.documents.models import DocumentVersion
from dpolens.engine.embedding import DEFAULT_MODEL, get_model
from dpolens.engine.embedding.encode import Embedder, ensure_cached
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import Actor
from dpolens.engine.logs.queries import purge_expired
from dpolens.engine.originals import Directory, strays
from dpolens.engine.session import create_db_engine, session_from
from dpolens.settings import Settings
from dpolens.telemetry import get_logger

telemetry = get_logger(__name__)

INDEX = "index"
MAINTENANCE = "maintenance"
QUEUES = (INDEX, MAINTENANCE)
STRAY_GRACE_SECONDS = 24 * 60 * 60
"""An original no version points at is kept for a day, so an upload in progress keeps its file."""

# The connector is replaced when the worker starts. A request never opens it: it queues jobs and
# reads their status on its own transaction's connection, which needs no pool of its own.
app = App(connector=SyncPsycopgConnector())


@dataclass
class Runtime:
    """What the worker's jobs share: its settings, one engine, and the model once loaded."""

    settings: Settings
    engine: Engine
    loaded: list[Embedder] = field(default_factory=list)

    def embedder(self) -> Embedder:
        if not self.loaded:
            model = get_model(DEFAULT_MODEL)
            ensure_cached(model)
            self.loaded.append(
                Embedder(model, intra_op_num_threads=self.settings.intra_op_num_threads)
            )
        return self.loaded[0]


running: list[Runtime] = []


def runtime() -> Runtime:
    if not running:
        raise RuntimeError("Jobs run in the worker: start it with `dpolens worker`.")
    return running[0]


@app.task(
    name="dpolens.index_version",
    queue=INDEX,
    retry=RetryStrategy(max_attempts=3, wait=30),
)
def index_version(version_id: str) -> int:
    """Embed what is published and not yet embedded, which is the version just published."""
    current = runtime()
    with session_from(current.engine) as session:
        result = build_index(session, current.embedder(), skip_embedded=True, create_index=False)
    telemetry.info("worker.indexed", version=version_id, embedded=result.embedded)
    return result.embedded


@app.periodic(cron="17 3 * * *", periodic_id="daily-purge")
@app.task(name="dpolens.daily_purge", queue=MAINTENANCE, queueing_lock="daily-purge")
def daily_purge(timestamp: int) -> dict[str, int]:
    """Delete what the instance promised not to keep, once a day."""
    current = runtime()
    with session_from(current.engine) as session:
        sessions = purge_ended(session, lifetimes=lifetimes_of(current.settings))
        links = purge_expired_links(session)
        questions = purge_expired(session, actor=Actor(via="worker"))
        referenced = set(
            session.scalars(
                select(DocumentVersion.source_key).where(DocumentVersion.source_key.is_not(None))
            )
        )
    originals = Directory(current.settings.originals_dir)
    stray = strays(originals, {key for key in referenced if key}, STRAY_GRACE_SECONDS)
    for key in stray:
        originals.remove(key)
    counts = {"questions": questions, "sessions": sessions, "links": links, "originals": len(stray)}
    telemetry.info("worker.purged", **counts)
    return counts


def queue_indexing(session: Session, version_id: uuid.UUID) -> int:
    """Queue the embedding of a published version, in the session's own transaction."""
    connection = session.connection().connection.driver_connection
    return index_version.configure(
        connection=connection, queueing_lock=f"index-{version_id}"
    ).defer(version_id=str(version_id))


def job_status(session: Session, job_id: int) -> str | None:
    """A job's status, `todo`, `doing`, `succeeded` or `failed`, or None once it is gone."""
    connection = session.connection().connection.driver_connection
    try:
        return app.job_manager.get_job_status(job_id, connection=connection).value
    except NoResult:
        return None


def purge_on_start() -> None:
    """The daily purge, run once as the worker starts. A failure is logged, and the worker
    starts anyway: its other jobs do not depend on it, and the next round tries again."""
    try:
        daily_purge(timestamp=int(time.time()))
    except Exception as failure:
        telemetry.warning("worker.purge_failed", error=type(failure).__name__)


def conninfo(settings: Settings) -> str:
    """The database URL as libpq reads it, which is what Procrastinate's pool is given."""
    return str(settings.database_url).replace("postgresql+psycopg://", "postgresql://", 1)


def run_worker(settings: Settings, queues: tuple[str, ...] = QUEUES) -> None:
    """Run jobs until stopped. A stop lets the jobs in hand finish first."""
    running.append(Runtime(settings=settings, engine=create_db_engine(settings)))
    try:
        purge_on_start()
        with app.replace_connector(PsycopgConnector(conninfo=conninfo(settings))) as worker:
            telemetry.info("worker.started", queues=list(queues))
            worker.run_worker(queues=list(queues), install_signal_handlers=True)
    finally:
        current = running.pop()
        for loaded in current.loaded:
            loaded.close()
        current.engine.dispose()
        telemetry.info("worker.stopped")
