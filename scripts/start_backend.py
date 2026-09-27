"""Start the matching local service without changing settings or user data."""
import argparse
import importlib.util
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    if sys.version_info[:2] != (3, 12):
        parser.error('Use Python 3.12 and the supplied dependency list.')
    missing = [name for name in ('uvicorn', 'fastapi', 'openai', 'pydantic_settings', 'PIL', 'faiss', 'sentence_transformers') if importlib.util.find_spec(name) is None]
    if missing:
        parser.error('Install backend/requirements-lock-windows-py312.txt in this environment first; missing: '+', '.join(missing))
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'backend'))
    import uvicorn
    uvicorn.run('main:app', host='127.0.0.1', port=args.port, workers=1)


if __name__ == '__main__':
    main()
