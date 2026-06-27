# Third-Party Notices

This project uses only the Python standard library at runtime, plus external
FFmpeg tools. Standalone builds may also contain the PyInstaller bootloader,
the Python runtime, and Tcl/Tk runtime files.

This file is a practical attribution and redistribution checklist, not legal
advice.

## Project Code

No project license is currently granted in this repository. Unless a `LICENSE`
file is added later, the application source code and assets remain all rights
reserved by their copyright holder.

## FFmpeg and ffprobe

- Project: https://ffmpeg.org/
- Legal page: https://ffmpeg.org/legal.html
- Source code: https://ffmpeg.org/download.html

The application runs `ffmpeg` and `ffprobe` as external executables through
Python `subprocess`. It does not link to FFmpeg libraries.

The repository does not commit FFmpeg binaries. Build scripts can bundle local
FFmpeg binaries from:

```text
vendor/windows/ffmpeg.exe
vendor/windows/ffprobe.exe
vendor/macos/ffmpeg
vendor/macos/ffprobe
```

The Windows binaries used during local testing were from Gyan FFmpeg builds:

- Build site: https://www.gyan.dev/ffmpeg/builds/
- Tested version string:
  `2026-06-15-git-44d082edc8-essentials_build-www.gyan.dev`
- Tested configuration included:
  `--enable-gpl --enable-version3 --enable-static --enable-libx264`

Because that tested build enables GPL/version3 components, treat those bundled
FFmpeg/ffprobe binaries as GPLv3-or-later binaries. If you bundle a different
FFmpeg build, check its own `ffmpeg -version` output and license terms.

When redistributing a build that contains FFmpeg/ffprobe, distribute the
app together with this notice and provide the corresponding FFmpeg license
texts and source-code access required by that FFmpeg build.

## x264

- Project: https://www.videolan.org/developers/x264.html
- Source code: https://code.videolan.org/videolan/x264

The tested Gyan FFmpeg build includes `libx264`. x264 is licensed under
GPLv2-or-later, and its presence is one of the reasons the tested FFmpeg binary
must be treated as GPL.

## PyInstaller

- Project: https://pyinstaller.org/
- Source code: https://github.com/pyinstaller/pyinstaller
- License information: https://pyinstaller.org/en/stable/license.html

PyInstaller is used only to build standalone executables/app bundles. Those
standalone builds include the PyInstaller bootloader. PyInstaller is licensed
under GPLv2-or-later with a bootloader exception that permits packaging
non-GPL applications.

## Python

- Project: https://www.python.org/
- License: https://docs.python.org/3/license.html

Standalone builds may contain parts of the Python runtime. Python is distributed
under the Python Software Foundation License and related historical licenses.

## Tcl/Tk

- Project: https://www.tcl.tk/
- License: https://www.tcl.tk/software/tcltk/license.html

The GUI uses Python `tkinter`, which depends on Tcl/Tk. Standalone GUI builds
may contain Tcl/Tk runtime files.
