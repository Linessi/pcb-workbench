"""One writer process, serialized atomic transactions, immutable revision arrays."""
import copy
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


class Repository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = threading.RLock()
        self.handle = None
        self.state = None

    def open(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / "writer.lock"
        self.handle = lock_path.open("a+b")
        self.handle.seek(0)
        self.handle.write(b"0")
        self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError("便签服务只允许一个写入进程；请使用 --workers 1。") from exc
        try:
            path = self.root / "store.json"
            self.state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
                "schema_version": 1, "boards": {}, "notes": {}, "attachments": {}, "jobs": {}, "drafts": {}, "packages": {},
            }
            if self.state.get("schema_version") != 1:
                import shutil
                shutil.copy2(path, self.root / f"unsupported-schema-{uid()}.backup.json")
                raise RuntimeError("便签数据版本不受支持；已备份，未覆盖原数据。")
            for folder in ("attachments", "packages"):
                (self.root / folder).mkdir(exist_ok=True)
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None

    def read(self):
        with self.lock:
            if self.state is None or self.handle is None:
                raise RuntimeError("便签服务尚未启动")
            return copy.deepcopy(self.state)

    @contextmanager
    def transaction(self):
        with self.lock:
            state = self.read()
            yield state
            path = self.root / "store.json"
            tmp = self.root / f".{uid()}.tmp"
            try:
                with tmp.open("x", encoding="utf-8") as stream:
                    json.dump(state, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Disk verification occurs before committing the in-memory view.
                if json.loads(tmp.read_text(encoding="utf-8")) != state:
                    raise OSError("便签写入核验失败")
                os.replace(tmp, path)
                self.state = state
            finally:
                tmp.unlink(missing_ok=True)

    def file(self, folder, name):
        base = self.root / folder
        path = base / name
        if base.is_symlink() or path.is_symlink() or path.resolve().parent != base.resolve() or base.resolve().parent != self.root:
            raise ValueError("文件路径不在便签存储范围内")
        return path
