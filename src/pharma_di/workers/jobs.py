"""Background job manager and task execution (IMPLEMENTATION_PLAN.md P9).
Runs the LangGraph pipeline asynchronously off the HTTP request/response cycle,
providing job creation, thread-pool execution, progress tracking, and status polling.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Callable
import uuid

from pharma_di.graph.build import compiled_graph
from pharma_di.graph.state import PipelineState
from pharma_di.schemas.api import JobResponse, JobStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobManager:
    """In-process asynchronous job manager backed by a ThreadPoolExecutor."""

    def __init__(self, max_workers: int = 2) -> None:
        self._max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pipeline-worker")
        self._jobs: dict[str, JobResponse] = {}
        self._lock = threading.Lock()

    def _get_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor._shutdown:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers, thread_name_prefix="pipeline-worker"
                )
            return self._executor

    def submit_job(
        self,
        input_path: str | Path,
        document_id: str | None = None,
        debug: bool = False,
        callback: Callable[[JobResponse], None] | None = None,
    ) -> JobResponse:
        input_path = Path(input_path)
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        doc_id = document_id or f"{input_path.stem}-{uuid.uuid4().hex[:8]}"

        job = JobResponse(
            job_id=job_id,
            document_id=doc_id,
            source_file=str(input_path),
            status=JobStatus.queued,
            progress_stage="queued",
            created_at=_now(),
        )

        with self._lock:
            self._jobs[job_id] = job

        executor = self._get_executor()
        executor.submit(self._run_job, job_id, input_path, doc_id, debug, callback)
        return job

    def _run_job(
        self,
        job_id: str,
        input_path: Path,
        document_id: str,
        debug: bool,
        callback: Callable[[JobResponse], None] | None = None,
    ) -> None:
        with self._lock:
            if job_id not in self._jobs:
                return
            job = self._jobs[job_id]
            job.status = JobStatus.processing
            job.progress_stage = "ingest"

        try:
            initial_state = PipelineState(
                source_file=str(input_path),
                document_id=document_id,
                debug=debug,
            )
            graph = compiled_graph()
            result = graph.invoke(initial_state)
            final_state = PipelineState.model_validate(result)

            with self._lock:
                job.status = JobStatus.completed if not final_state.errors else JobStatus.completed
                job.progress_stage = "completed"
                job.trace = final_state.trace
                job.errors = final_state.errors
                job.completed_at = _now()
                job.routed_to_review = final_state.routed_to_review
                job.persisted = final_state.persisted

        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job.status = JobStatus.failed
                job.progress_stage = "failed"
                job.errors.append(str(exc))
                job.completed_at = _now()

        if callback:
            try:
                callback(job)
            except Exception:  # noqa: BLE001
                pass

    def get_job(self, job_id: str) -> JobResponse | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job.model_copy()
            return None

    def list_jobs(self) -> list[JobResponse]:
        with self._lock:
            return [job.model_copy() for job in self._jobs.values()]

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            self._executor.shutdown(wait=wait)


# Global singleton instance for the FastAPI app
default_job_manager = JobManager()
