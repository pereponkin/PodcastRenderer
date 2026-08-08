# FFmpeg Source and Build Information

Podcast Renderer release packages bundle separate `ffmpeg` and `ffprobe`
executables from Shaka Project static FFmpeg binaries release `n8.1.2-1`:

- Binary release: <https://github.com/shaka-project/static-ffmpeg-binaries/releases/tag/n8.1.2-1>
- Build scripts and configuration: <https://github.com/shaka-project/static-ffmpeg-binaries/tree/n8.1.2-1>
- FFmpeg source: <https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz>
- x264 source: <https://code.videolan.org/videolan/x264>

The release is built with GPL and version 3 components, including `libx264`.
Treat the bundled FFmpeg executables as GPLv3-or-later binaries. The complete
GPLv3 license text is included in `licenses/GPL-3.0.txt`.

The application invokes these executables as separate programs. It does not
link to FFmpeg libraries. Podcast Renderer source code is available at:

<https://github.com/pereponkin/PodcastRenderer>

If an upstream source URL becomes unavailable, open an issue in that repository
and identify the Podcast Renderer release whose corresponding source you need.
