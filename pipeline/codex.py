"""Local authenticated Astra inference, with independent exit/event/schema checks."""
import json
import threading
import uuid
import time

from .runtime import clean, timestamp, write_json


def _schema(value):
    if isinstance(value, list):
        return [_schema(v) for v in value]
    if not isinstance(value, dict):
        return value
    value = {k: _schema(v) for k, v in value.items()}
    if 'prefixItems' in value:
        items = value.pop('prefixItems')
        if any(item != items[0] for item in items):
            raise ValueError('Inference schema requires homogeneous coordinate arrays')
        value['items'] = items[0]
    return value


class Codex:
    def __init__(self, config, runtime):
        self.config = config
        self.runtime = runtime
        self.slots = threading.BoundedSemaphore(config.concurrency)

    def infer(self, prompt, images, output_type, purpose):
        with self.slots:
            return self._infer(prompt, images, output_type, purpose)

    def _infer(self, prompt, images, output_type, purpose):
        started = time.monotonic()
        call_id = uuid.uuid4().hex
        directory = self.runtime.output / 'inference' / call_id
        directory.mkdir(parents=True)
        schema_path = directory / 'schema.json'
        final_path = directory / 'final.json'
        write_json(schema_path, _schema(output_type.model_json_schema()))
        write_json(directory / 'input.json', {"prompt": prompt, "images": [p.name for p in images]})
        argv = [self.config.executable, 'exec', '--ignore-user-config', '--ephemeral',
                '--skip-git-repo-check', '--sandbox', 'read-only', '--model', self.config.model,
                '-c', 'model_reasoning_effort=' + json.dumps(self.config.reasoning),
                '--cd', str(directory), '--output-schema', str(schema_path),
                '--output-last-message', str(final_path), '--json']
        for image in images:
            argv.extend(['--image', str(image)])
        argv.append('-')
        call = {"id": call_id, "purpose": purpose, "provider": "local Codex", "model": self.config.model,
                "settings": {"reasoning": self.config.reasoning, "sandbox": "read-only",
                             "ignore_user_config": True, "ephemeral": True}, "started_at": timestamp()}
        try:
            stdout = self.runtime.process(argv, directory, prompt, self.config.timeout_seconds)
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            write_json(directory / 'events.json', events)
            completed = [e for e in events if e.get('type') == 'turn.completed']
            if not completed or any(e.get('type') in ('turn.failed', 'error') for e in events):
                raise RuntimeError('Codex did not report a successful turn')
            call['usage'] = [e.get('usage') for e in completed]
            call['thread_ids'] = [e['thread_id'] for e in events if 'thread_id' in e]
            # Final JSON is checked even when the launcher and turn report success.
            result = output_type.model_validate_json(final_path.read_text())
            call['output'] = result.model_dump(mode='json')
            return result
        except Exception as error:
            call['failure'] = clean(str(error))
            raise RuntimeError('Astra inference unavailable or invalid; inspect inference evidence') from None
        finally:
            call['elapsed_seconds'] = time.monotonic() - started
            if final_path.exists():
                final_path.write_text(clean(final_path.read_text()))
            self.runtime.record(call)
