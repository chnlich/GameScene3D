"""Content-addressed Meshy requests; an unacknowledged POST is never repeated.

Request receipts reserve conservative credit bounds before submission. The file
lock covers all workers sharing an output directory. Reconcile ambiguous receipts
with the provider before any operator-authorized resubmission.
"""
import base64
import fcntl
import hashlib
import json
import os
import struct
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

from .runtime import clean, digest, timestamp, write_json


def read_key(config):
    path = config.key_file
    if path.stat().st_mode & 0o077:
        raise RuntimeError('Meshy key file must be owner-only')
    key = path.read_text().strip()
    if not key:
        raise RuntimeError('Meshy key file is empty')
    return key


def triangle_count(path):
    with path.open('rb') as stream:
        magic, version, length = struct.unpack('<4sII', stream.read(12))
        if magic != b'glTF' or version != 2 or length != path.stat().st_size:
            raise RuntimeError('Generated asset is not a complete GLB 2 file')
        size, kind = struct.unpack('<II', stream.read(8))
        if kind != 0x4E4F534A:
            raise RuntimeError('Generated GLB lacks a JSON header')
        document = json.loads(stream.read(size))
    faces = 0
    for mesh in document['meshes']:
        for primitive in mesh['primitives']:
            if primitive.get('mode', 4) != 4:
                raise RuntimeError('Generated asset has unsupported nontriangle geometry')
            accessor = primitive['indices'] if 'indices' in primitive else primitive['attributes']['POSITION']
            faces += document['accessors'][accessor]['count'] // 3
    return faces


class Meshy:
    def __init__(self, config, runtime):
        self.config = config
        self.runtime = runtime
        self.root = runtime.output / 'provider'
        self.root.mkdir(exist_ok=True)

    def _key(self):
        return read_key(self.config)

    def _request(self, route, payload):
        key = self._key()
        request = urllib.request.Request(self.config.endpoint + route,
                                        data=None if payload is None else json.dumps(payload).encode(),
                                        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=self.runtime.remaining(self.config.request_timeout_seconds)) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                body = error.read().decode(errors='replace').replace(key, '[credential omitted]')
                if error.code != 429 or attempt == 4:
                    raise RuntimeError(f'Meshy HTTP {error.code}: {clean(body)}') from None
                retry_after = error.headers.get('Retry-After')
                delay = 2 ** (attempt + 1)
                if retry_after is not None:
                    seconds = float(retry_after) if retry_after.isdigit() else parsedate_to_datetime(retry_after).timestamp() - time.time()
                    delay = max(delay, seconds)
                self.runtime.record({'provider': 'Meshy', 'route': route, 'http_status': 429,
                                     'retry': attempt + 1, 'delay_seconds': delay, 'at': timestamp()})
                if delay >= self.runtime.remaining():
                    raise TimeoutError('Meshy Retry-After exceeds generation deadline') from None
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as error:
                raise RuntimeError('Meshy transport failed; submission outcome may be unknown: ' + clean(str(error))) from None

    def _reserve(self, directory, route, payload, bound):
        spending = self.config.spending
        if not spending.authorization or spending.max_submissions == 0:
            raise RuntimeError('Meshy paid-call budget is not authorized')
        with (self.root / 'budget.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            receipts = [json.loads(p.read_text()) for p in self.root.glob('*/request.json')]
            if ((spending.max_submissions is not None and len(receipts) >= spending.max_submissions) or
                (spending.max_credits is not None and sum(r['reserved_credits'] for r in receipts) + bound > spending.max_credits)):
                raise RuntimeError('Meshy authorized spending limit would be exceeded')
            receipt = {"route": route, "input": payload, "reserved_credits": bound, "started_at": timestamp()}
            # Exclusive creation precedes the potentially charged network call.
            with (directory / 'request.json').open('x') as stream:
                json.dump(clean(receipt), stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())

    def task(self, route, payload, bound):
        key = digest({'endpoint': self.config.endpoint, 'route': route, 'payload': payload})
        directory = self.root / key
        directory.mkdir(exist_ok=True)
        # Serialize identical content even when concurrent assets ask for it.
        with (directory / 'call.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            receipt = directory / 'response.json'
            started = time.monotonic()
            call = {'id': key, 'provider': 'Meshy', 'model': self.config.model,
                    'route': route, 'started_at': timestamp(), 'input': payload,
                    'credits': None, 'credits_reason': 'Provider has not reported consumption'}
            try:
                if receipt.exists():
                    response = json.loads(receipt.read_text())
                    self.runtime.record({'provider': 'Meshy', 'purpose': 'submission receipt reuse',
                                         'route': route, 'call': key})
                else:
                    if (directory / 'request.json').exists():
                        raise RuntimeError('Ambiguous prior Meshy submission; reconcile provider task before retry')
                    self._reserve(directory, route, payload, bound)
                    response = self._request(route, payload)
                    write_json(receipt, response)
                # Staging v2 remesh returns the task object directly. Its v1 read
                # representation exposes the same ID with model_urls for downloads.
                task_id = response['id'] if route == '/openapi/v2/remesh' else response['result']
                if not isinstance(task_id, str) or not task_id or '/' in task_id:
                    raise RuntimeError('Meshy submission did not return a task ID; reconcile receipt')
                call['task_id'] = task_id
                poll_route = '/openapi/v1/remesh' if route == '/openapi/v2/remesh' else route
                call['poll_route'] = poll_route
                while True:
                    result = self._request(poll_route + '/' + task_id, None)
                    write_json(directory / 'task.json', result)
                    with (directory / 'polls.jsonl').open('a') as stream:
                        stream.write(json.dumps(clean({'at': timestamp(), 'elapsed_seconds': time.monotonic()-started, 'response': result})) + '\n')
                    status = result['status']
                    call['output'] = result
                    call['credits'] = result.get('consumed_credits')
                    if call['credits'] is not None:
                        call['credits_reason'] = None
                        if self.config.spending.max_credits is not None and call['credits'] > bound:
                            raise RuntimeError('Provider consumption exceeded configured bound; halt and reconcile budget')
                    if status == 'SUCCEEDED':
                        return task_id, result, directory
                    if status in ('FAILED', 'CANCELED', 'EXPIRED'):
                        raise RuntimeError('Required Meshy task failed: ' + clean(str(result.get('task_error'))))
                    if status not in ('PENDING', 'IN_PROGRESS'):
                        raise RuntimeError('Unknown Meshy task status: ' + str(status))
                    time.sleep(min(self.config.poll_seconds, self.runtime.remaining()))
            except Exception as error:
                call['failure'] = clean(str(error))
                raise
            finally:
                call['elapsed_seconds'] = time.monotonic() - started
                self.runtime.record(call)

    def download(self, url, path):
        if path.exists():
            self.runtime.record({'provider': 'Meshy download', 'purpose': 'reused existing file',
                                 'path': path.relative_to(self.runtime.output).as_posix()})
            return
        request = urllib.request.Request(url, headers={'User-Agent': 'GameFrame3D/1.0'})
        part = path.with_suffix('.part')
        try:
            with urllib.request.urlopen(request, timeout=self.runtime.remaining(self.config.request_timeout_seconds)) as response, part.open('wb') as stream:
                while chunk := response.read(1024 * 1024):
                    self.runtime.remaining()
                    stream.write(chunk)
            if part.stat().st_size == 0:
                raise RuntimeError('Empty Meshy asset download')
            part.replace(path)
        except Exception as error:
            self.runtime.record({'provider': 'Meshy download', 'failure': clean(str(error))})
            raise RuntimeError('Required asset download failed; inspect evidence') from None

    def asset(self, asset, image):
        budget = self.config.spending
        if image is not None and asset.reference_crop is not None:
            from PIL import Image
            with Image.open(image) as original:
                w, h = original.size
                x0, y0, x1, y1 = asset.reference_crop
                box = (round(x0*w), round(y0*h), round(x1*w), round(y1*h))
                if box[0] >= box[2] or box[1] >= box[3]:
                    raise ValueError('Reference crop has no pixels')
                crop = original.crop(box).convert('RGB')
                crop_path = self.runtime.output / 'references' / (asset.id + '.png')
                crop_path.parent.mkdir(exist_ok=True)
                crop.save(crop_path)
            payload = {'ai_model': self.config.model, 'model_type': 'standard', 'should_texture': True,
                       'enable_pbr': True, 'should_remesh': False, 'target_formats': ['glb'],
                       'pose_mode': 'a-pose' if asset.articulated else '',
                       'image_url': 'data:image/png;base64,' + base64.b64encode(crop_path.read_bytes()).decode()}
            task_id, result, directory = self.task('/openapi/v1/image-to-3d', payload, budget.image_credits_upper_bound)
        else:
            payload = {'mode': 'preview', 'prompt': asset.description, 'ai_model': self.config.model,
                       'should_remesh': False, 'target_formats': ['glb'],
                       'pose_mode': 'a-pose' if asset.articulated else ''}
            preview_id, _, _ = self.task('/openapi/v2/text-to-3d', payload, budget.preview_credits_upper_bound)
            task_id, result, directory = self.task('/openapi/v2/text-to-3d',
                {'mode': 'refine', 'preview_task_id': preview_id, 'enable_pbr': True,
                 'texture_prompt': asset.description}, budget.refine_credits_upper_bound)
        model = directory / 'model.glb'
        self.download(result['model_urls']['glb'], model)
        rig = None
        rig_input_id = task_id
        if self.config.rigging_enabled and asset.articulated:
            faces = triangle_count(model)
            # Staging rigging rejects inputs above 320,000 faces; preserve the original
            # textured surface and simplify only the provider's skeleton source.
            if faces > 320000:
                remesh_payload = {'input_task_id': task_id,
                                  'target_polycount': self.config.rig_target_polycount,
                                  'topology': 'triangle'}
                if self.config.remesh_route == '/openapi/v1/remesh':
                    remesh_payload['target_formats'] = ['glb']
                rig_input_id, remesh_result, remesh_dir = self.task(self.config.remesh_route,
                    remesh_payload, budget.remesh_credits_upper_bound)
                remeshed = remesh_dir / 'model.glb'
                self.download(remesh_result['model_urls']['glb'], remeshed)
                remeshed_faces = triangle_count(remeshed)
                write_json(remesh_dir / 'geometry.json', {'original_faces': faces, 'remeshed_faces': remeshed_faces})
                if remeshed_faces > 320000:
                    raise RuntimeError('Remeshed model still exceeds the provider rigging face limit')
            _, result, rig_dir = self.task('/openapi/v1/rigging',
                {'input_task_id': rig_input_id, 'height_meters': asset.height_meters}, budget.rig_credits_upper_bound)
            rig = rig_dir / 'rigged.glb'
            self.download(result['result']['rigged_character_glb_url'], rig)
        return {'model': model.relative_to(self.runtime.output).as_posix(),
                'rig': None if rig is None else rig.relative_to(self.runtime.output).as_posix(),
                'sha256': hashlib.sha256(model.read_bytes()).hexdigest(), 'task_id': task_id,
                'rig_input_task_id': rig_input_id if rig is not None else None}
