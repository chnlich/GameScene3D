import fcntl
import importlib
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from server.config import Config
from server.files import atomic_bytes, atomic_json, contained_file, public_safe, publish_result, validate

LOG = logging.getLogger(__name__)
JOB_ID = re.compile(r"^[0-9a-f]{32}$")


class TaskError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.payload = {"code": code, "message": message}
        validate("Error", self.payload)


def capability(config: Config):
    if not config.generation_config or not config.generation_config.is_file():
        return None, "Generation configuration is missing; set generation_config in the root YAML."
    for executable in ("codex", "blender"):
        if shutil.which(executable) is None:
            return None, f"Required {executable} executable is missing from PATH."
    try:
        module = importlib.import_module("pipeline.runner")
    except ModuleNotFoundError:
        LOG.info("Generation module or its dependency is unavailable", exc_info=True)
        return None, "Install pipeline.runner and its declared dependencies."
    except Exception:
        LOG.exception("Generation module could not be imported")
        return None, "Pipeline import failed; inspect the local server log."
    generate = getattr(module, "generate", None)
    if not callable(generate):
        return None, "pipeline.runner must provide generate(request, output_dir, on_progress)."
    return generate, "Local prerequisites detected; full 3D generation has not been verified by health."


class Runtime:
    def __init__(self, config: Config):
        self.config = config
        self.lock = threading.RLock()
        self.pending = 0
        self.pool = None
        self.owner_file = None

    def start(self):
        self.config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.owner_file = (self.config.data_dir / ".owner.lock").open("a+")
        try:
            fcntl.flock(self.owner_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner_file.close()
            raise RuntimeError("Data directory already belongs to a live server") from None
        try:
            # The exclusive OS lock proves that every previous owner has exited.
            for directory in self.config.data_dir.iterdir():
                if JOB_ID.fullmatch(directory.name):
                    job = self.read(directory.name)
                    if job["status"] in ("queued", "running"):
                        job.update(status="failed", result=None, error={
                            "code": "interrupted",
                            "message": "Server stopped before completion. Files are preserved; submit a new job.",
                        })
                        self.save(job)
            self.owner_file.seek(0)
            self.owner_file.truncate()
            self.owner_file.write(json.dumps({"pid": os.getpid(), "instance": uuid.uuid4().hex}))
            self.owner_file.flush()
            self.pool = ThreadPoolExecutor(max_workers=self.config.max_concurrency, thread_name_prefix="generation")
        except Exception:
            self.owner_file.close()
            raise

    def close(self):
        # Keep ownership until executing calls finish and write their final snapshot.
        self.pool.shutdown(wait=True)
        self.owner_file.close()

    def directory(self, job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id):
            raise TaskError(404, "not_found", "Job not found.")
        directory = self.config.data_dir / job_id
        if directory.is_symlink() or not directory.is_dir():
            raise TaskError(404, "not_found", "Job not found.")
        return directory

    def read(self, job_id: str):
        path = contained_file(self.directory(job_id), "job.json")
        job = json.loads(path.read_text())
        validate("Job", job)
        if job["status"] == "succeeded":
            try:
                result = json.loads(contained_file(self.directory(job_id), "result.json").read_text())
                job["result"] = publish_result(result, self.directory(job_id), f"/artifacts/{job_id}/")
            except Exception:
                LOG.exception("Completed artifacts are unavailable for job %s", job_id)
                job.update(status="failed", result=None, error={
                    "code": "artifacts_unavailable",
                    "message": "Completed files are missing or invalid. Inspect preserved job files and regenerate the scene.",
                })
                self.save(job)
        return job

    def save(self, job):
        validate("Job", job)
        atomic_json(self.directory(job["id"]) / "job.json", job)

    def submit(self, prompt: str, image: bytes | None, extension: str | None):
        generate, note = capability(self.config)
        if generate is None:
            raise TaskError(503, "generation_unavailable", note)
        with self.lock:
            if self.pending >= self.config.max_concurrency + self.config.max_queued:
                raise TaskError(503, "busy", "Generation capacity is full. Retry after a current job completes.")
            job_id = uuid.uuid4().hex
            directory = self.config.data_dir / job_id
            directory.mkdir(mode=0o700)
            original = f"original.{extension}" if image is not None else None
            job = {
                "id": job_id, "status": "queued",
                "progress": {"phase": "queued", "message": "Waiting for an execution slot.", "fraction": None},
                "input": {"prompt": prompt, "image_url": f"/artifacts/{job_id}/{original}" if original else None},
                "result": None, "error": None,
            }
            if image is not None:
                atomic_bytes(directory / original, image)
            # Local paths and generation configuration are intentionally absent from snapshots.
            atomic_json(directory / "request.json", job["input"])
            self.save(job)
            request = {
                "id": job_id, "prompt": prompt,
                "image_path": str((directory / original).resolve()) if original else None,
                "config_path": str(self.config.generation_config.resolve()),
            }
            validate("GenerationRequest", request)
            self.pending += 1
            try:
                future = self.pool.submit(self.execute, generate, request, directory, original)
                future.add_done_callback(self.report_worker_error)
            except Exception:
                self.pending -= 1
                job.update(status="failed", error={"code": "scheduling_failed", "message": "Unable to schedule generation; restart the local server."})
                self.save(job)
                LOG.exception("Failed to schedule job %s", job_id)
                raise TaskError(503, "scheduling_failed", job["error"]["message"]) from None
            return job

    @staticmethod
    def report_worker_error(future):
        error = future.exception()
        if error is not None:
            LOG.critical("Worker could not persist its final status", exc_info=(type(error), error, error.__traceback__))

    def execute(self, generate, request: dict, directory: Path, original: str | None):
        started = time.monotonic()
        job = self.read(request["id"])
        callback_error = None
        accepting_progress = True

        def progress(snapshot):
            nonlocal callback_error
            with self.lock:
                try:
                    if not accepting_progress:
                        raise ValueError("Progress callback arrived after generate returned")
                    validate("Progress", snapshot)
                    public_safe(snapshot)
                    job["progress"] = json.loads(json.dumps(snapshot))
                    self.save(job)
                except Exception as error:
                    callback_error = error
                    LOG.exception("Invalid progress for job %s", job["id"])
                    raise

        try:
            job["status"] = "running"
            job["progress"] = {"phase": "starting", "message": "Generation call executing.", "fraction": None}
            self.save(job)
            result = generate(request, directory, progress)
            with self.lock:
                accepting_progress = False
                if callback_error is not None:
                    raise ValueError("Pipeline ignored a rejected progress callback") from callback_error
            validate("Result", result)
            if result["artifacts"]["original"] != original:
                raise ValueError("Result.original must refer to the retained input")
            if original is not None and result["camera"] is not None:
                with Image.open(directory / original) as image:
                    aspect = image.width / image.height
                if abs(result["camera"]["aspect_ratio"] - aspect) > 1e-6 * aspect:
                    raise ValueError("Camera aspect ratio disagrees with original image")
            result["elapsed_seconds"] = time.monotonic() - started
            published = publish_result(result, directory, f"/artifacts/{job['id']}/")
            atomic_json(directory / "result.json", result)
            job.update(status="succeeded", result=published, error=None)
            job["progress"] = {"phase": "complete", "message": "Validated scene and evidence are available.", "fraction": 1}
            self.save(job)
        except Exception:
            LOG.exception("Generation failed for job %s", job["id"])
            with self.lock:
                accepting_progress = False
                job.update(status="failed", result=None, error={
                    "code": "generation_failed",
                    "message": "Generation or output validation failed. Inspect the local server log and preserved job evidence; correct the pipeline or configuration and retry.",
                })
                self.save(job)
        finally:
            with self.lock:
                self.pending -= 1

    def artifact(self, job_id: str, reference: str):
        job = self.read(job_id)
        urls = [job["input"]["image_url"]]
        if job["result"] is not None:
            urls.extend(job["result"]["artifacts"].values())
        if f"/artifacts/{job_id}/{quote(reference, safe='/')}" not in urls:
            raise TaskError(404, "not_found", "Artifact not found.")
        return contained_file(self.directory(job_id), reference)
