# Podcast Renderer

Small Python GUI app that renders a YouTube-compatible MP4 from one audio file and up to three silent video files: intro, loop, outro. Video inputs can be MP4, MOV, or M4V as long as FFmpeg can read them.

The `Audio` source may also be a common video container such as MP4, MOV, MKV, AVI, WebM, MPEG, TS, or WMV. Only its first audio stream is used.

## Run on Windows

1. Install Python 3 from <https://www.python.org/downloads/windows/>.
2. Install FFmpeg:
   - easiest: `winget install Gyan.FFmpeg`
   - or download a build from <https://www.gyan.dev/ffmpeg/builds/> and add its `bin` folder to `PATH`
   - alternatively put `ffmpeg.exe` and `ffprobe.exe` next to `main.py`
3. Open PowerShell in this folder.
4. Run:

```powershell
python main.py
```

## Run on macOS

1. Install Python 3 from <https://www.python.org/downloads/macos/> or with Homebrew:

```bash
brew install python
```

2. Install FFmpeg:

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

Install PyInstaller:

```bash
python -m pip install pyinstaller
```

Windows:

```powershell
python -m PyInstaller --onefile --windowed --name PodcastRenderer main.py
```

The executable will be in `dist\PodcastRenderer.exe`. FFmpeg still needs to be installed on `PATH`, or you can place `ffmpeg.exe` and `ffprobe.exe` next to the executable.

## Build Self-Contained Windows EXE

Put Windows FFmpeg binaries here:

```text
vendor/windows/ffmpeg.exe
vendor/windows/ffprobe.exe
```

Then run in PowerShell:

```powershell
.\build_windows.ps1
```

The single-file executable will be:

```text
dist\PodcastRenderer.exe
dist\PodcastRenderer-windows.zip
dist\THIRD_PARTY_NOTICES.md
```

Send `dist\PodcastRenderer-windows.zip` when you redistribute the bundled
Windows build. It contains the executable and third-party notices.

macOS:

```bash
python3 -m pip install pyinstaller
python3 -m PyInstaller --windowed --name PodcastRenderer main.py
```

The app bundle will be in `dist/PodcastRenderer.app`. FFmpeg still needs to be installed on `PATH`, or placed inside/next to the app and resolved by your launch setup.

## Build Self-Contained macOS App

On a Mac, put self-contained macOS `ffmpeg` and `ffprobe` binaries here:

```text
vendor/macos/ffmpeg
vendor/macos/ffprobe
```

Then run:

```bash
chmod +x vendor/macos/ffmpeg vendor/macos/ffprobe
bash build_mac.sh
```

The script builds:

```text
dist/PodcastRenderer.app
dist/PodcastRenderer-macOS.zip
dist/THIRD_PARTY_NOTICES.md
```

Send `dist/PodcastRenderer-macOS.zip` to the Mac user. It contains the app and
third-party notices. If `vendor/macos` is missing, the script can use `ffmpeg`
and `ffprobe` from `PATH`, but Homebrew binaries may require Homebrew libraries
on the target Mac.

## License and Third-Party Notices

No project license is currently granted in this repository. Unless a `LICENSE`
file is added later, the application source code and assets remain all rights
reserved by their copyright holder.

Runtime operation depends on FFmpeg/ffprobe. Standalone builds may bundle
FFmpeg/ffprobe, PyInstaller bootloader files, Python runtime files, and Tcl/Tk
runtime files. See `THIRD_PARTY_NOTICES.md` before redistributing binaries.

## Notes

- Paths with spaces, Cyrillic, and special characters are passed to FFmpeg safely through Python `subprocess` argument lists.
- Rendering runs as one FFmpeg process and can be cancelled from the GUI.
- If rendering fails, the GUI log shows the command and FFmpeg output.
