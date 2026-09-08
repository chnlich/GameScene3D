"""Read-only HTTP serving for a standalone finished-demo export."""

import argparse
from contextlib import ExitStack
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import os
from pathlib import Path
import shutil
import stat
from urllib.parse import quote, unquote


def open_contained(root_fd: int, parts: list[str]) -> int:
    # Descriptor-relative opens refuse symlinks atomically, including ancestors.
    with ExitStack() as stack:
        parent = root_fd
        for part in parts[:-1]:
            parent = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            stack.callback(os.close, parent)
        if not parts:
            return os.dup(root_fd)
        return os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )


class ExportServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], root_fd: int):
        self.root_fd = root_fd
        super().__init__(address, ExportHandler)


class ExportHandler(BaseHTTPRequestHandler):
    server_version = "StaticExport"
    sys_version = ""

    def parse_request(self):
        if not super().parse_request():
            return False
        if self.command not in ("GET", "HEAD"):
            self.send_response(405)
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        raw_path, separator, query = self.path.partition("?")
        try:
            if not raw_path.startswith("/"):
                raise ValueError("Invalid request path")
            parts = []
            for segment in raw_path.split("/"):
                part = unquote(segment, errors="strict")
                if part in (".", "..") or any(
                    char in part for char in ("/", "\\", "%", "#", ":")
                ) or any(ord(char) < 32 or ord(char) == 127 for char in part):
                    raise ValueError("Invalid request path")
                if part:
                    parts.append(part)
        except ValueError:
            self.send_error(404)
            return

        with ExitStack() as stack:
            try:
                fd = open_contained(self.server.root_fd, parts)
                stack.callback(os.close, fd)
                metadata = os.fstat(fd)
                is_directory = stat.S_ISDIR(metadata.st_mode)
                if is_directory:
                    fd = open_contained(fd, ["index.html"])
                    stack.callback(os.close, fd)
                    metadata = os.fstat(fd)
                    filename = "index.html"
                else:
                    filename = parts[-1]
                    if raw_path.endswith("/"):
                        self.send_error(404)
                        return
                if not stat.S_ISREG(metadata.st_mode):
                    self.send_error(404)
                    return
            except OSError as error:
                if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EACCES):
                    self.send_error(404)
                    return
                self.send_error(500)
                raise

            # A directory URL needs its slash for relative viewer asset URLs.
            if is_directory and not raw_path.endswith("/"):
                self.send_response(301)
                location = "/" + "/".join(quote(p, safe="") for p in parts) + "/"
                self.send_header("Location", location + separator + query)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            media_type = {
                ".js": "text/javascript",
                ".mjs": "text/javascript",
                ".wasm": "application/wasm",
                ".glb": "model/gltf-binary",
            }.get(Path(filename).suffix.lower())
            if parts in (["api", "examples"], ["api", "health"]):
                media_type = "application/json"
            if media_type is None:
                media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(metadata.st_size))
            self.send_header("Last-Modified", self.date_time_string(metadata.st_mtime))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command == "GET":
                with os.fdopen(os.dup(fd), "rb") as stream:
                    shutil.copyfileobj(stream, self.wfile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    with ExitStack() as stack:
        anchor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, anchor)
        root_fd = open_contained(anchor, list(args.directory.absolute().parts[1:]))
        stack.callback(os.close, root_fd)
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            parser.error("--directory must be an existing directory")
        server = stack.enter_context(ExportServer((args.host, args.port), root_fd))
        print(f"Serving static export on {args.host}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Static export server stopped", flush=True)


if __name__ == "__main__":
    main()
