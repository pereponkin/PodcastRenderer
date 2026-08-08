# Podcast Renderer

[![Tests](https://github.com/pereponkin/PodcastRenderer/actions/workflows/tests.yml/badge.svg)](https://github.com/pereponkin/PodcastRenderer/actions/workflows/tests.yml)

Small Python GUI app that renders a YouTube-compatible MP4 from one audio file and up to three silent video files: intro, loop, outro. Video inputs can be MP4, MOV, or M4V as long as FFmpeg can read them.

The `Audio` source may also be a common video container such as MP4, MOV, MKV, AVI, WebM, MPEG, TS, or WMV. Only its first audio stream is used.

## Install Without Python

Download the files only from the official
[Podcast Renderer releases](https://github.com/pereponkin/PodcastRenderer/releases)
page. Release packages already contain Python, Tkinter, FFmpeg, and ffprobe.
Users do not need Python, Homebrew, FFmpeg, or programming tools.

### Windows

1. Download `PodcastRenderer-<version>-Windows-Setup.exe` from the latest
   release.
2. Open it and follow the installer. Administrator rights are not required.
3. Start **Podcast Renderer** from the Start menu.

The installer is intentionally unsigned because this project does not use a
paid code-signing certificate. Windows SmartScreen may show **Windows protected
your PC**. When the file came from the official release page above:

1. Click **More info**.
2. Check that the app name is `PodcastRenderer-<version>-Windows-Setup.exe`.
3. Click **Run anyway**.

`PodcastRenderer-<version>-Windows-Portable.zip` is also available. Extract it
to a normal folder and run `PodcastRenderer.exe`; no installation is needed.

### macOS

Choose the package for the Mac processor:

- `PodcastRenderer-<version>-macOS-Apple-Silicon.dmg` for M1, M2, M3,
  M4, and newer Apple chips;
- `PodcastRenderer-<version>-macOS-Intel.dmg` for older Intel Macs.

Then:

1. Open the DMG and drag `PodcastRenderer.app` to **Applications**.
2. Open **Applications** and try to launch PodcastRenderer once.
3. macOS may say that Apple could not verify the app. Click **Done**; do not
   move it to Trash.
4. Open **System Settings > Privacy & Security** and scroll to **Security**.
5. Click **Open Anyway** next to PodcastRenderer, then confirm **Open** and
   enter the Mac password if requested.

macOS saves this exception, so later launches use a normal double-click. This
warning appears because the free build has no paid Apple Developer ID, not
because the app requires Python or Terminal. Do not disable Gatekeeper and do
not run `sudo` or `xattr` commands. The DMG also contains `INSTALL.txt` with the
same instructions.

Every release includes `SHA256SUMS.txt`. Advanced users can compare a downloaded
file's SHA-256 with that list. The app processes selected media locally and does
not upload it.

## Run From Source on Windows

1. Install Python 3 from <https://www.python.org/downloads/windows/>.
2. Install FFmpeg 5.1 or newer:
   - easiest: `winget install Gyan.FFmpeg`
   - or download a build from <https://www.gyan.dev/ffmpeg/builds/> and add its `bin` folder to `PATH`
   - alternatively put `ffmpeg.exe` and `ffprobe.exe` next to `main.py`
3. Open PowerShell in this folder.
4. Run:

```powershell
python main.py
```

## Run From Source on macOS

1. Install Python 3 with Tkinter from <https://www.python.org/downloads/macos/> or with Homebrew:

```bash
brew install python-tk
```

2. Install FFmpeg 5.1 or newer:

```bash
brew install ffmpeg
```

3. Open Terminal in this folder and run:

```bash
python3 main.py
```

## What It Produces

Video selection rules:

- One selected video file: it is looped for the full audio duration.
- `INTRO + LOOP + OUTRO`: intro starts at 00:00, loop fills the middle, outro ends with the audio.
- `INTRO + LOOP`: intro starts at 00:00, loop fills the rest.
- `LOOP + OUTRO`: loop fills the beginning, outro ends with the audio.
- `INTRO + OUTRO` without `LOOP` is not allowed because there is no middle filler.
- With one video, its display resolution and frame rate are preserved as the output target.
- With multiple videos, the output uses the complete resolution of the source with the lowest pixel count and the lowest source frame rate. Sources are never enlarged; aspect ratio is preserved with padding when needed, including portrait video.

The output is saved in the selected `OUTPUT` folder as:

```text
<audio_basename>_video.mp4
```

The output folder is filled from the audio file folder automatically, but you can change it in the `OUTPUT` field. If the output file exists, the app writes `_1`, `_2`, etc. It does not silently overwrite.

The final file is MP4 with H.264 High Profile, `yuv420p`, source-derived resolution and constant frame rate, 2048k video bitrate (`maxrate` 2048k, `bufsize` 4096k, x264 `veryfast` preset), and `+faststart`.

AAC input audio is copied into the MP4 without re-encoding. Other audio formats are encoded to AAC at 48 kHz, 320k, stereo; mono non-AAC input is converted to stereo.

## Build Standalone with PyInstaller

Install the pinned build dependency:

```bash
python -m pip install -r requirements-build.txt
```

Windows:

```powershell
python -m PyInstaller --onefile --windowed --name PodcastRenderer main.py
```

The executable will be in `dist\PodcastRenderer.exe`. FFmpeg still needs to be installed on `PATH`, or you can place `ffmpeg.exe` and `ffprobe.exe` next to the executable.

## Build Windows Packages

Download the pinned, verified Windows FFmpeg binaries:

```powershell
.\scripts\fetch_ffmpeg_windows.ps1
```

Install [Inno Setup 6 or 7](https://jrsoftware.org/isdl.php), then run:

```powershell
.\build_windows_installer.ps1
```

The build verifies FFmpeg and creates:

```text
dist\PodcastRenderer.exe
dist\PodcastRenderer-Windows-Portable.zip
dist\PodcastRenderer-Setup.exe
```

macOS:

```bash
python3 -m pip install -r requirements-build.txt
python3 -m PyInstaller --windowed --name PodcastRenderer main.py
```

The app bundle will be in `dist/PodcastRenderer.app`. FFmpeg still needs to be installed on `PATH`, or placed inside/next to the app and resolved by your launch setup.

## Build macOS Packages

Run these commands on the target architecture Mac. The fetch script downloads
the pinned static binaries for Apple Silicon or Intel automatically and verifies
their SHA-256 values:

```bash
bash scripts/fetch_ffmpeg_macos.sh
bash build_mac.sh
```

The script builds:

```text
dist/PodcastRenderer.app
dist/PodcastRenderer-<version>-macOS-Apple-Silicon.dmg
dist/PodcastRenderer-<version>-macOS-Apple-Silicon.zip
```

Intel builds use `Intel` instead of `Apple-Silicon` in the file names. The app
is ad-hoc signed for bundle integrity but is not Developer ID signed or
notarized.

## Automated Releases

Pushing a version tag such as `v1.2.0` starts `.github/workflows/release.yml`.
The tag must match `APP_VERSION` in `main.py`. GitHub Actions then:

1. runs all unit tests on Windows, Apple Silicon macOS, and Intel macOS;
2. builds the Windows installer and portable archive;
3. builds Apple Silicon and Intel DMG/ZIP packages;
4. generates SHA-256 checksums;
5. publishes every package and notice as a GitHub Release.

The release workflow downloads FFmpeg `n8.1.2-1` and Inno Setup `7.0.2` from
immutable upstream releases and verifies their recorded SHA-256 values before
using them.

## License and Third-Party Notices

No project license is currently granted in this repository. Unless a `LICENSE`
file is added later, the application source code and assets remain all rights
reserved by their copyright holder.

Runtime operation depends on FFmpeg/ffprobe. Standalone builds may bundle
FFmpeg/ffprobe, PyInstaller bootloader files, Python runtime files, and Tcl/Tk
runtime files. Redistributable packages include `THIRD_PARTY_NOTICES.md`,
`FFMPEG_SOURCE_OFFER.md`, and the applicable license texts from `licenses/`.

## Notes

- Paths with spaces, Cyrillic, and special characters are passed to FFmpeg safely through Python `subprocess` argument lists.
- Media analysis and rendering can be cancelled from the GUI; the active ffprobe or FFmpeg process is terminated.
- Closing the window cancels and waits for the active media process.
- Each ffprobe analysis is limited to 15 seconds, so an unreadable source cannot leave the app waiting indefinitely.
- FFmpeg renders to a hidden partial MP4. Failed or cancelled partial files are removed, and the final name is published only after success.
- If rendering fails, the GUI log shows the command and FFmpeg output.

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the test suite on Windows, Apple Silicon macOS, and Intel
macOS for every push to `main` and every pull request.
