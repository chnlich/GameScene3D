import io
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser
from python_multipart.exceptions import MultipartParseError

from server.config import Config
from server.examples import examples
from server.files import ROOT, contained_file, public_safe, validate
from server.runtime import Runtime, TaskError, capability

LOG = logging.getLogger(__name__)


def error_response(status: int, code: str, message: str):
    payload = {"code": code, "message": message}
    validate("Error", payload)
    return JSONResponse(payload, status_code=status)


class BodyLimit:
    """Bound actual request bytes, including chunked bodies, before multipart parsing."""
    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise TaskError(422, "request_too_large", "Request exceeds max_request_bytes.")
            return message

        await self.app(scope, limited_receive, send)


class CompleteMultipartParser(MultiPartParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.complete = False

    def on_end(self):
        super().on_end()
        self.complete = True

    async def parse(self):
        form = await super().parse()
        # python-multipart finalize() does not require a closing boundary.
        if not self.complete:
            await form.close()
            raise MultipartParseError("Missing final multipart boundary")
        return form


def decode_image(data: bytes, config: Config):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise TaskError(422, "invalid_image", "Image must be actual PNG, JPEG or WebP data.")
            if image.width * image.height > config.max_image_pixels:
                raise TaskError(422, "image_too_large", "Decoded image exceeds max_image_pixels.")
            extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image.format]
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return extension
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        LOG.info("Rejected malformed image: %s", type(error).__name__)
        raise TaskError(422, "invalid_image", "Image could not be decoded. Supply a valid PNG, JPEG or WebP.") from None


def file_response(root: Path, reference: str):
    try:
        path = contained_file(root, reference)
    except (ValueError, OSError):
        LOG.debug("Rejected missing or uncontained asset", exc_info=True)
        raise TaskError(404, "not_found", "Asset not found.") from None
    media_type = {".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm", ".glb": "model/gltf-binary"}.get(path.suffix)
    return FileResponse(path, media_type=media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream", headers={"X-Content-Type-Options": "nosniff"})


def create_app(config: Config, root: Path = ROOT):
    runtime = Runtime(config)

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(runtime.start)
        try:
            yield
        finally:
            await run_in_threadpool(runtime.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime
    app.add_middleware(BodyLimit, limit=config.max_request_bytes)

    @app.exception_handler(TaskError)
    async def task_error(request, error):
        return JSONResponse(error.payload, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(422, "invalid_request", "Request does not match the required input format.")

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        status = 422 if error.status_code == 400 else error.status_code
        return error_response(status, "invalid_request" if status == 422 else "not_found", "Request is malformed or route is unavailable.")

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        LOG.error("HTTP operation failed", exc_info=(type(error), error, error.__traceback__))
        return error_response(500, "internal_error", "Operation failed; inspect the local server log and configuration.")

    @app.get("/api/health")
    def health():
        generate, note = capability(config)
        value = {"ok": True, "generation_available": generate is not None, "generation_note": note}
        validate("Health", value)
        return value

    @app.post("/api/jobs", status_code=202)
    async def submit(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
            raise TaskError(422, "invalid_request", "Use multipart/form-data with image and/or prompt.")
        try:
            parser = CompleteMultipartParser(request.headers, request.stream(), max_files=1, max_fields=1, max_part_size=config.max_prompt_chars * 4)
            form = await parser.parse()
            try:
                if any(key not in ("image", "prompt") for key in form) or len(form.multi_items()) != len(form):
                    raise TaskError(422, "invalid_request", "Use only one image and one prompt field.")
                prompt = form.get("prompt", "")
                upload = form.get("image")
                if not isinstance(prompt, str) or (upload is not None and not isinstance(upload, UploadFile)):
                    raise TaskError(422, "invalid_request", "Prompt must be text and image must be a file.")
                prompt = prompt.strip()
                if len(prompt) > config.max_prompt_chars:
                    raise TaskError(422, "prompt_too_large", "Prompt exceeds max_prompt_chars.")
                try:
                    public_safe(prompt)
                except ValueError:
                    LOG.info("Rejected private data in prompt")
                    raise TaskError(422, "private_input", "Remove credentials and local filesystem paths from the prompt.") from None
                data = None
                extension = None
                if upload is not None:
                    data = await upload.read(config.max_upload_bytes + 1)
                    if len(data) > config.max_upload_bytes:
                        raise TaskError(422, "image_too_large", "Image exceeds max_upload_bytes.")
                    extension = await run_in_threadpool(decode_image, data, config)
                if not prompt and data is None:
                    raise TaskError(422, "empty_input", "Supply a nonempty prompt or valid image.")
                return await run_in_threadpool(runtime.submit, prompt, data, extension)
            finally:
                await form.close()
        except (MultipartParseError, MultiPartException):
            LOG.info("Rejected malformed multipart data", exc_info=True)
            raise TaskError(422, "invalid_request", "Malformed multipart body.") from None

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return runtime.read(job_id)

    @app.get("/api/examples")
    def list_examples():
        return examples(root)

    @app.get("/artifacts/{job_id}/{reference:path}")
    def artifact(job_id: str, reference: str):
        try:
            path = runtime.artifact(job_id, reference)
        except (ValueError, OSError):
            LOG.debug("Rejected artifact path", exc_info=True)
            raise TaskError(404, "not_found", "Artifact not found.") from None
        return file_response(path.parent, path.name)

    @app.get("/demo/{reference:path}")
    def demo(reference: str):
        return file_response(root, "demo/" + reference)

    @app.get("/vendor/three/{reference:path}")
    def vendor(reference: str):
        return file_response(root, "node_modules/three/" + reference)

    @app.get("/{reference:path}")
    def ui(reference: str):
        if reference.split("/", 1)[0] in ("api", "artifacts", "demo", "vendor"):
            raise TaskError(404, "not_found", "Route not found.")
        if not (root / "web/index.html").is_file():
            raise TaskError(503, "ui_not_ready", "Viewer files are not installed yet.")
        return file_response(root, "web/" + (reference or "index.html"))

    return app
