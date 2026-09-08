import argparse
from pathlib import Path

import uvicorn

from server.app import create_app
from server.config import load_config


def main():
    parser = argparse.ArgumentParser(description="GameFrame3D HTTP server")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = load_config(args.config.resolve())
    uvicorn.run(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
