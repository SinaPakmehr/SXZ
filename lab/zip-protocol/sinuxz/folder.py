"""Stream a Windows-friendly, PAX TAR directory through SXZ2 without staging TAR."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Generator, Iterator

from .stream import BRIDGE, NESTED, StreamOptions, StreamStats, _decode_chunks, _header, pack_stream, unpack_stream

BLOCK = 1 << 20
Progress = Callable[[str, int], None]


@dataclass(frozen=True)
class Entry:
    path: Path
    name: str
    info: os.stat_result

    @property
    def is_dir(self) -> bool:
        return stat.S_ISDIR(self.info.st_mode)


def inventory(root: Path) -> list[Entry]:
    """Read path metadata, failing loudly for inaccessible or special entries."""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("input is not a directory")
    entries = []

    def walk(path: Path) -> None:
        info = path.lstat()
        if getattr(info, "st_file_attributes", 0) & 0x400 or stat.S_ISLNK(info.st_mode):
            raise ValueError(f"symbolic link, junction or reparse point is not supported: {path}")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError(f"unsupported entry: {path}")
        entries.append(Entry(path, path.relative_to(root.parent).as_posix(), info))
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir(), key=lambda p: (p.name.casefold(), p.name)):
                walk(child)

    walk(root)
    return entries


def _tar_parts(entries: list[Entry]) -> Generator[bytes, None, None]:
    for entry in entries:
        arc = tarfile.TarInfo(entry.name)
        arc.mode = entry.info.st_mode & 0o777
        arc.mtime = entry.info.st_mtime
        if entry.is_dir:
            arc.type = tarfile.DIRTYPE
        else:
            arc.size = entry.info.st_size
        yield arc.tobuf(format=tarfile.PAX_FORMAT, encoding="utf-8", errors="strict")
        if entry.is_dir:
            continue
        remaining = arc.size
        with entry.path.open("rb") as src:
            while remaining:
                block = src.read(min(remaining, BLOCK))
                if not block:
                    raise ValueError(f"file was truncated during packing: {entry.path}")
                remaining -= len(block)
                yield block
            final = os.fstat(src.fileno())
            if ((final.st_size, final.st_mtime_ns, final.st_ino)
                    != (entry.info.st_size, entry.info.st_mtime_ns, entry.info.st_ino)):
                raise ValueError(f"file changed during packing: {entry.path}")
        if arc.size % 512:
            yield bytes(-arc.size % 512)
    yield bytes(1024)


class _Parts(io.RawIOBase):
    def __init__(self, parts: Iterator[bytes], progress: Progress | None = None) -> None:
        self.parts = parts
        self.pending = memoryview(b"")
        self.digest = hashlib.sha256()
        self.progress = progress
        self.total = 0
        self.next_report = 1 << 30

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        out = memoryview(buffer)
        pos = 0
        while pos < len(out):
            if not self.pending:
                part = next(self.parts, None)
                if part is None:
                    break
                self.pending = memoryview(part)
            count = min(len(self.pending), len(out) - pos)
            out[pos:pos + count] = self.pending[:count]
            self.pending = self.pending[count:]
            pos += count
        self.digest.update(out[:pos])
        self.total += pos
        if self.progress is not None and self.total >= self.next_report:
            self.progress("pack", self.total)
            self.next_report += 1 << 30
        return pos

    def close(self) -> None:
        close = getattr(self.parts, "close", None)
        if close:
            close()
        super().close()


class _DigestWriter:
    def __init__(self, progress: Progress | None = None) -> None:
        self.digest = hashlib.sha256()
        self.progress = progress
        self.total = 0
        self.next_report = 1 << 30

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        self.total += len(data)
        if self.progress is not None and self.total >= self.next_report:
            self.progress("verify", self.total)
            self.next_report += 1 << 30
        return len(data)


def pack_folder(root: Path, destination: Path, options: StreamOptions, *, progress: Progress | None = None) -> dict:
    """Pack and fully verify a new archive. Never replace an existing output."""
    root = root.resolve(strict=True)
    destination = destination.absolute()
    if destination.resolve().is_relative_to(root):
        raise ValueError("archive must be outside the input directory")
    entries = inventory(root)
    original = sum(entry.info.st_size for entry in entries if not entry.is_dir)
    start = perf_counter()
    # A failed run removes only the new output that this invocation created.
    with destination.open("xb") as out:
        try:
            raw = _Parts(_tar_parts(entries), progress)
            with io.BufferedReader(raw, buffer_size=BLOCK) as src:
                report = pack_stream(src, out, options)
            out.flush()
            packed = perf_counter() - start
        except BaseException:
            out.close()
            destination.unlink(missing_ok=True)
            raise
    try:
        start = perf_counter()
        digest = _DigestWriter(progress)
        with destination.open("rb") as archive:
            decoded = unpack_stream(archive, digest, max_output=report.first.original_size)
        elapsed = perf_counter() - start
        if decoded.original_size != report.first.original_size or raw.digest.digest() != digest.digest.digest():
            raise ValueError("directory TAR round-trip did not match")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {
        "source": str(root), "archive": str(destination), "files": sum(not e.is_dir for e in entries),
        "directories": sum(e.is_dir for e in entries), "input_bytes": original,
        "tar_bytes": report.first.original_size, "archive_bytes": report.stored_size,
        "pack_seconds": packed, "verify_seconds": elapsed, "frames": report.first.frames,
        "probes": report.first.probes, "formula_bytes": report.first.formula_bytes,
        "codecs": dict(report.first.codecs), "tar_sha256": digest.digest.hexdigest(),
        "options": asdict(options),
    }


def _member_parts(name: str) -> list[str]:
    parts = name.split("/")
    if any(not part or part in (".", "..") or part[-1] in ". "
           or any(c in '\\:<>|?*"' or ord(c) < 32 for c in part) for part in parts):
        raise ValueError(f"unsafe TAR member path: {name!r}")
    if os.name == "nt":
        import ntpath
        # Python < 3.13 may not provide isreserved. Keep the common Windows
        # device aliases out of the path regardless of extension.
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³")
        isreserved = getattr(ntpath, "isreserved", lambda _: False)
        if any(isreserved(part) or part.split(".")[0].rstrip().upper() in reserved for part in parts):
            raise ValueError(f"reserved TAR member path: {name!r}")
    return parts


def restore_folder(archive: Path, destination: Path, *, max_output: int | None = None) -> dict:
    """Restore a single-layer PAX TAR SXZ2 to a new directory, without an intermediate TAR."""
    if max_output is not None and max_output < 0:
        raise ValueError("max_output must be nonnegative")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"restore directory already exists: {destination}")
    files = directories = 0
    stats = StreamStats()
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".sxz-restore-") as work:
        stage = Path(work, "contents")
        stage.mkdir()
        with archive.open("rb") as src:
            flags, size, window = _header(src)
            if flags & NESTED:
                raise ValueError("unpack-folder supports the single-layer archives made by pack-folder")
            chunks = _decode_chunks(src, size, window, max_output, bool(flags & BRIDGE), stats)
            with io.BufferedReader(_Parts(chunks), buffer_size=BLOCK) as decoded:
                try:
                    with tarfile.open(fileobj=decoded, mode="r|") as archive_tar:
                        for member in archive_tar:
                            dest = stage.joinpath(*_member_parts(member.name))
                            if member.isdir():
                                dest.mkdir()
                                directories += 1
                            elif member.isreg() and not member.issparse():
                                with archive_tar.extractfile(member) as item, dest.open("xb") as out:
                                    shutil.copyfileobj(item, out, BLOCK)
                                os.utime(dest, (member.mtime, member.mtime))
                                files += 1
                            else:
                                raise ValueError(f"unsupported TAR member: {member.name!r}")
                except tarfile.TarError as exc:
                    raise ValueError("invalid TAR inside SXZ2") from exc
                # TAR may stop at its own end marker before the SXZ2 footer.
                while decoded.read(BLOCK):
                    pass
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"restore directory already exists: {destination}")
        stage.rename(destination)
    return {"destination": str(destination), "files": files, "directories": directories,
            "tar_bytes": stats.original_size, "archive_bytes": stats.stored_size}
