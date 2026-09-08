"""Deadline-bound calls and sanitized evidence retained beside generated assets."""
import hashlib
import json
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()
                if not any(word in k.lower() for word in ("authorization", "key_file", "config_path", "email"))}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'(?:https?://|data:)[^\s"<>]+', '[URL omitted]', value)
        value = re.sub(r'(?<!\w)/(?:home|tmp|mnt|Users|private|var)/[^\s"<>]+', '[host path omitted]', value)
        value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email omitted]', value)
        value = re.sub(r'(?i)(?:bearer\s+\S+|(?:sk|msy)[-_][A-Za-z0-9_-]{12,})', '[credential omitted]', value)
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(clean(value), indent=2, ensure_ascii=False))
    temporary.replace(path)


class Runtime:
    def __init__(self, output, seconds):
        self.output = output
        self.started = time.monotonic()
        self.end = self.started + seconds
        self.lock = threading.Lock()
        self.attempt = uuid.uuid4().hex
        evidence_path = self.output / 'evidence.json'
        self.evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {
            "started_at": timestamp(), "calls": [], "changes": [],
            "cost_usd": None, "cost_reason": "Codex account billing unavailable; Meshy credits are not USD"}
        self.evidence.setdefault('attempts', []).append({'id': self.attempt, 'started_at': timestamp()})
        self.save()

    def remaining(self, limit=None):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Generation deadline exceeded; evidence retained")
        return remaining if limit is None else min(remaining, limit)

    def save(self):
        write_json(self.output / 'evidence.json', self.evidence)

    def record(self, call):
        with self.lock:
            self.evidence['calls'].append(clean(call))
            self.save()

    def process(self, argv, directory, stdin, limit):
        started = time.monotonic()
        call = {"provider": "local", "started_at": timestamp(), "argv": argv,
                "directory": directory.relative_to(self.output).as_posix()}
        try:
            result = subprocess.run(argv, input=stdin, text=True, capture_output=True,
                                    cwd=directory, timeout=self.remaining(limit), check=False)
            stdout, stderr = result.stdout, result.stderr
            call['exit_code'] = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or b''
            stderr = error.stderr or b''
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors='replace')
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors='replace')
            call['failure'] = 'Process exceeded deadline'
            raise TimeoutError('Local process exceeded deadline; evidence retained') from None
        except OSError as error:
            stdout, stderr = '', str(error)
            call['failure'] = type(error).__name__
            raise RuntimeError('Local executable unavailable; inspect evidence') from None
        finally:
            (directory / 'stdout.log').write_text(clean(stdout))
            (directory / 'stderr.log').write_text(clean(stderr))
            call['elapsed_seconds'] = time.monotonic() - started
            self.record(call)
        if result.returncode != 0:
            raise RuntimeError('Local process failed; inspect retained stdout/stderr')
        return stdout
