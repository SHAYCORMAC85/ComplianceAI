"""Lifespan-owned workers for the local SQLite inspection queue."""
import asyncio
from contextlib import asynccontextmanager
import logging
import sqlite3
from backend.db.schema import exclusive_owner

from backend.config import settings
from backend.db.store import RecoveryError, document_store
from backend.services.compliance_service import compliance_service
from backend.services.inspection_progress import observer

logger = logging.getLogger(__name__)


class InspectionWorkers:
    def __init__(self, store, service):
        self.store = store
        self.service = service
        self.wake = asyncio.Event()
        self.stopping = False

    async def run(self):
        from backend.api.routes_documents import restore_original
        while not self.stopping:
            self.wake.clear()
            try:
                doc_id = self.store.claim_job()
            except sqlite3.OperationalError:
                logger.warning("Inspection queue temporarily unavailable.")
                await asyncio.sleep(1)
                continue
            if doc_id is None:
                await self.wake.wait()
                continue
            token = observer.set(lambda stage, outcome, retry_at: self.store.job_progress(doc_id, stage, outcome, retry_at))
            try:
                document = self.store.load_job_document(doc_id, restore_original, settings.LLM_PROVIDER.lower())
                await self.service.analyze_document(document)
            except Exception as exc:
                message = str(exc) if isinstance(exc, RecoveryError) else "Inspection failed. Retry this inspection."
                # Disk-full and lock errors can also prevent recording the failure.
                # Keep the job recoverable until a short write succeeds or shutdown cancels us.
                delay = 1
                while not self.stopping:
                    try:
                        self.store.fail_if_processing(doc_id, message)
                        break
                    except sqlite3.OperationalError:
                        logger.warning("Cannot persist inspection failure; storage is unavailable.")
                        await asyncio.sleep(delay)
                        delay = min(15, delay * 2)
                logger.warning("Inspection %s failed (%s)", doc_id, type(exc).__name__)
            finally:
                observer.reset(token)
            await asyncio.sleep(0)


@asynccontextmanager
async def lifespan(app):
    # OS releases this file lock even if the owning process is killed.
    with exclusive_owner(document_store.path.parent):
        document_store.recover_jobs()
        workers = InspectionWorkers(document_store, compliance_service)
        app.state.workers = workers
        tasks = [asyncio.create_task(workers.run()) for _ in range(settings.INSPECTION_WORKERS)]
        try:
            yield
        finally:
            workers.stopping = True
            workers.wake.set()
            _, pending = await asyncio.wait(tasks, timeout=settings.WORKER_SHUTDOWN_SECONDS)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
