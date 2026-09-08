"""GLM gateway inference over an OpenAI-compatible chat completions endpoint."""
import base64
import json
import threading
import time
import urllib.error
import urllib.request
import uuid

from .codex import _schema
from .runtime import clean, timestamp, write_json


def _strip_wire_bounds(value):
    if isinstance(value, list):
        return [_strip_wire_bounds(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: _strip_wire_bounds(item) for key, item in value.items()
            if key not in ('minimum', 'exclusiveMinimum', 'maximum', 'exclusiveMaximum')}


def _embed_schema(prompt, output_type):
    trailer = ('\n\nReply with exactly ONE JSON object validating against the JSON Schema below. '
               'Every required field must be present; use an empty list where a required list '
               'has no entries. Output no prose and no markdown fences.\n\nJSON Schema:\n')
    return prompt + trailer + json.dumps(_strip_wire_bounds(_schema(output_type.model_json_schema())))


def _first_json_object(content):
    text = content.strip()
    if text.startswith('```'):
        newline = text.find('\n')
        text = text[newline + 1:] if newline >= 0 else text[3:]
        stripped = text.rstrip()
        if stripped.endswith('```'):
            text = stripped[:-3]
    start = 0
    while True:
        start = text.find('{', start)
        if start < 0:
            return None
        depth = 0
        quoted = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:index + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
        start += 1


class Glm:
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
        write_json(directory / 'input.json', {"prompt": prompt, "images": [p.name for p in images]})
        message = prompt
        if not self.config.structured_decoding:
            message = _embed_schema(prompt, output_type)
        if images:
            content = [{"type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()}}
                       for image in images]
            content.append({"type": "text", "text": message})
        else:
            content = message
        payload = {"model": self.config.model, "messages": [{"role": "user", "content": content}],
                   "max_tokens": int(self.config.max_tokens)}
        if self.config.structured_decoding:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": purpose,
                "schema": _strip_wire_bounds(_schema(output_type.model_json_schema()))}}
        if not self.config.enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        call = {"id": call_id, "purpose": purpose, "provider": "GLM gateway", "model": self.config.model,
                "settings": {"max_tokens": self.config.max_tokens, "timeout_seconds": self.config.timeout_seconds},
                "started_at": timestamp()}
        if self.config.structured_decoding:
            call['settings']["response_format"] = "json_schema"
        else:
            call['settings']["structured_decoding"] = False
        call['settings']["enable_thinking"] = self.config.enable_thinking
        call['settings']["wire_bounds_stripped"] = True
        try:
            request = urllib.request.Request(self.config.endpoint + '/chat/completions',
                                             data=json.dumps(payload).encode(), method='POST',
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                write_json(directory / 'response.json', {"invalid_body": raw})
                raise
            write_json(directory / 'response.json', body)
            choice = body['choices'][0]
            if choice['finish_reason'] == 'length':
                raise RuntimeError('GLM response hit the max_tokens limit')
            call['usage'] = body.get('usage')
            if self.config.structured_decoding:
                result = output_type.model_validate_json(choice['message']['content'])
            else:
                candidate = _first_json_object(choice['message']['content'])
                if candidate is None:
                    raise RuntimeError('GLM reply contained no balanced JSON object')
                result = output_type.model_validate(candidate)
            call['output'] = result.model_dump(mode='json')
            return result
        except Exception as error:
            if isinstance(error, urllib.error.HTTPError):
                write_json(directory / 'response.json',
                           {"status": error.code, "body": error.read().decode(errors='replace')})
            call['failure'] = clean(str(error))
            raise RuntimeError('GLM inference unavailable or invalid; inspect inference evidence') from None
        finally:
            call['elapsed_seconds'] = time.monotonic() - started
            self.runtime.record(call)
