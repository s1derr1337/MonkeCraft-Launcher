import hashlib
import json
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QThread, Signal


class MRPackWorker(QThread):
    """Install files from a Modrinth .mrpack into a Minecraft instance directory."""

    status = Signal(str)
    progress = Signal(int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, pack_url, install_dir, state_file=None):
        super().__init__()
        self.pack_url = str(pack_url)
        self.install_dir = Path(install_dir)
        self.state_file = Path(state_file) if state_file else self.install_dir / "monkecraft_pack_state.json"

    @staticmethod
    def _safe_relative(value):
        p = PurePosixPath(str(value))
        if p.is_absolute() or not p.parts or any(part in ("..", "") for part in p.parts):
            raise ValueError(f"Unsafe path in pack: {value}")
        if p.parts and ":" in p.parts[0]:
            raise ValueError(f"Unsafe path in pack: {value}")
        return Path(*p.parts)

    @staticmethod
    def _hash_file(path, algorithm, expected):
        h = hashlib.new(algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().lower() == str(expected).lower()

    @classmethod
    def _matches_hashes(cls, path, hashes):
        if not hashes:
            return True
        usable = [(alg, expected) for alg, expected in hashes.items() if alg in ("sha1", "sha512")]
        return bool(usable) and any(cls._hash_file(path, alg, expected) for alg, expected in usable)

    def _download(self, url, target, hashes=None, retries=5, timeout=60):
        """Download to a .part file, resume where possible, verify, then atomically replace.

        Retry transient failures. Keep partial bytes between retries and worker runs;
        discard them if a server doesn't support Range or the completed hash is bad.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        headers = {"User-Agent": "MonkeCraft Launcher"}

        for attempt in range(retries):
            try:
                offset = tmp.stat().st_size if tmp.exists() else 0
                request_headers = dict(headers)
                if offset:
                    request_headers["Range"] = f"bytes={offset}-"

                req = urllib.request.Request(url, headers=request_headers)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    # If the server ignored Range, restart the partial file rather than append.
                    append = offset > 0 and getattr(response, "status", None) == 206
                    if offset and not append:
                        offset = 0
                    mode = "ab" if append else "wb"
                    with open(tmp, mode) as out:
                        shutil.copyfileobj(response, out, length=1024 * 1024)

                if hashes and not self._matches_hashes(tmp, hashes):
                    tmp.unlink(missing_ok=True)
                    raise ValueError("SHA hash does not match downloaded file")

                tmp.replace(target)
                return
            except Exception:
                if attempt + 1 >= retries:
                    raise
                # Keep a partial download for the next attempt, unless it failed hash verification.
                time.sleep(min(2 ** attempt, 8))

    def run(self):
        try:
            self.install_dir.mkdir(parents=True, exist_ok=True)
            archive_path = self.install_dir / ".monkecraft_pack_download.mrpack"
            self.status.emit("Загрузка modpack...")
            self._download(self.pack_url, archive_path, retries=5, timeout=60)

            with zipfile.ZipFile(archive_path, "r") as z:
                try:
                    index = json.loads(z.read("modrinth.index.json").decode("utf-8"))
                except KeyError:
                    raise ValueError("В архиве отсутствует modrinth.index.json")

                if index.get("formatVersion") != 1:
                    raise ValueError("Неподдерживаемый формат .mrpack index")

                previous = {}
                try:
                    if self.state_file.exists():
                        previous = json.loads(self.state_file.read_text(encoding="utf-8"))
                except Exception:
                    previous = {}

                old_managed = set(previous.get("managed_files", []))
                new_managed = set()
                files = index.get("files", [])
                total = max(1, len(files))

                for i, item in enumerate(files, 1):
                    rel = self._safe_relative(item.get("path", ""))
                    target = self.install_dir / rel
                    new_managed.add(rel.as_posix())
                    hashes = item.get("hashes", {})
                    verified = target.exists() and self._matches_hashes(target, hashes)

                    if not verified:
                        self.status.emit(f"Загрузка файла {i}/{len(files)}: {rel.as_posix()}")
                        urls = item.get("downloads", [])
                        if not urls:
                            raise ValueError(f"Нет ссылки для загрузки: {rel}")
                        last_error = None
                        downloaded = False
                        for url in urls:
                            try:
                                self._download(url, target, hashes=hashes, retries=5, timeout=60)
                                downloaded = True
                                break
                            except Exception as e:
                                last_error = e
                        if not downloaded:
                            raise RuntimeError(f"Не удалось скачать/проверить {rel}: {last_error}")
                    self.progress.emit(int(i * 70 / total))

                # Copy pack overrides. Track copied files so later updates can remove
                # only files previously owned by this pack, never arbitrary user files.
                override_prefix = str(index.get("overrides", "overrides")).strip("/")
                override_entries = [n for n in z.namelist() if n.startswith(override_prefix + "/") and not n.endswith("/")]
                for j, entry in enumerate(override_entries, 1):
                    rel_text = entry[len(override_prefix) + 1:]
                    rel = self._safe_relative(rel_text)
                    # Preserve the user's options.txt after the first successful install.
                    # IMPORTANT: keep it in new_managed so stale-file cleanup won't delete it.
                    if rel.as_posix().lower() == "options.txt" and previous.get("options_installed"):
                        new_managed.add(rel.as_posix())
                        continue
                    target = self.install_dir / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(entry) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    new_managed.add(rel.as_posix())
                    self.progress.emit(70 + int(j * 25 / max(1, len(override_entries))))

                # Remove files previously managed by MonkeCraft but absent from the new pack.
                for stale in old_managed - new_managed:
                    rel = self._safe_relative(stale)
                    target = self.install_dir / rel
                    try:
                        if target.is_file():
                            target.unlink()
                        parent = target.parent
                        while parent != self.install_dir and parent.exists():
                            try:
                                parent.rmdir()
                            except OSError:
                                break
                            parent = parent.parent
                    except Exception:
                        pass

                state = {
                    "pack_version": index.get("versionId", ""),
                    "managed_files": sorted(new_managed),
                    "options_installed": bool(previous.get("options_installed")) or any(
                        self._safe_relative(n[len(override_prefix) + 1:]).as_posix().lower() == "options.txt"
                        for n in override_entries
                    ),
                }
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

            try:
                archive_path.unlink()
            except Exception:
                pass
            self.progress.emit(100)
            self.finished_ok.emit("Modpack установлен/обновлён.")
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
