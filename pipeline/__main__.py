"""Pipeline-owned invocation for generation and local validation."""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from .runner import generate, verify_iteration
from .runtime import clean, timestamp, write_json


def main():
    parser = argparse.ArgumentParser(description='Generate and inspect a GameFrame3D scene')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', type=Path)
    parser.add_argument('--prompt-file', type=Path)
    parser.add_argument('--id', required=True)
    parser.add_argument('--verify-iteration', type=Path,
                        help='Reopen an output-relative iteration without inference or generation')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    invocation = args.output / 'invocations' / uuid.uuid4().hex
    invocation.mkdir(parents=True)
    write_json(invocation / 'command.json', {'argv': [sys.executable, '-m', 'pipeline', *sys.argv[1:]],
                                           'started_at': timestamp()})
    def progress(event):
        line = json.dumps(event)
        with (invocation / 'progress.jsonl').open('a') as stream:
            stream.write(line + '\n')
        print(line, flush=True)
    started = time.monotonic()
    try:
        if args.verify_iteration is not None:
            result = verify_iteration(str(args.config), args.output, args.verify_iteration)
            write_json(invocation / 'outcome.json', {'verification': result, 'elapsed_seconds': time.monotonic()-started})
            print(json.dumps(result, indent=2))
            return
        result = generate({'id': args.id, 'image_path': None if args.image is None else str(args.image.resolve()),
                       'prompt': '' if args.prompt_file is None else args.prompt_file.read_text(),
                       'config_path': str(args.config.resolve())}, args.output,
                          progress)
        write_json(invocation / 'outcome.json', {'result': result, 'elapsed_seconds': time.monotonic()-started})
        print(json.dumps(result, indent=2))
    except Exception as error:
        write_json(invocation / 'outcome.json', {'failure': clean(str(error)), 'elapsed_seconds': time.monotonic()-started})
        raise


if __name__ == '__main__':
    main()
