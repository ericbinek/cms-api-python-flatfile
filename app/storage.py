import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_data_dir = None


def _get_data_dir():
    global _data_dir
    if _data_dir is None:
        d = os.environ.get("DATA_DIR") or "./data"
        Path(d).mkdir(parents=True, exist_ok=True)
        _data_dir = Path(d).resolve()
    return _data_dir


def read_collection(filename):
    path = _get_data_dir() / filename
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        raise RuntimeError(f"Data file corrupted: {path}")
    return data if isinstance(data, list) else []


def write_collection(filename, items):
    path = _get_data_dir() / filename
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def with_lock():
    return _lock
