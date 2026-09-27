"""Check the built Windows archive and launch its extracted application."""

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def check_portable(archive_path: Path) -> None:
    repository = Path(__file__).resolve().parent.parent
    required = [Path("THIRD_PARTY_NOTICES.md"), Path("FFMPEG_SOURCE_OFFER.md")]
    required += [path.relative_to(repository) for path in (repository / "licenses").iterdir()
                 if path.is_file()]
    with tempfile.TemporaryDirectory(prefix="Podcast Renderer portable ") as temporary:
        extracted = Path(temporary) / "проверка распаковки"
        with zipfile.ZipFile(archive_path) as archive:
            if archive.getinfo("PodcastRenderer.exe").file_size == 0:
                raise RuntimeError("Portable executable is empty")
            for path in required:
                if archive.read(path.as_posix()) != (repository / path).read_bytes():
                    raise RuntimeError(f"Portable notice differs from source: {path}")
            archive.extractall(extracted)
        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment["PATH"] = str(Path(environment["SystemRoot"]) / "System32")
        subprocess.run([str(extracted / "PodcastRenderer.exe"), "--smoke-test"],
                       cwd=extracted, env=environment, check=True, timeout=60)
    print("Portable archive contents and application launch: OK")


if __name__ == "__main__":
    if sys.platform != "win32" or len(sys.argv) != 2:
        raise SystemExit("Usage on Windows: python scripts/check_windows_portable.py ARCHIVE.zip")
    check_portable(Path(sys.argv[1]).resolve())
