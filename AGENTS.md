# Project Facts

- `main.py` is the Tkinter GUI entry point; `render.py` owns the FFmpeg render pipeline and `media_probe.py` owns probing and binary discovery.
- The Windows release is portable only. `build_windows.ps1` builds the bundled one-file EXE and `PodcastRenderer-Windows-Portable.zip`; `.github/workflows/release.yml` publishes the versioned ZIP. There is no Windows installer build.
- macOS packages are built by `build_mac.sh` and the release workflow for Apple Silicon and Intel.
- Rendering keeps source AAC/ALAC by stream copy, converts other lossless audio to ALAC, and converts other lossy audio to AAC. The render job can cancel FFprobe/FFmpeg processes and publishes output only after validating the partial file.
- Video uses source-derived dimensions and rational frame rate. One loop period is encoded and repeated by stream copy; intro, outro, and a partial loop tail are encoded only when needed.
- `APP_VERSION` in `main.py` must match a release tag. Do not edit generated `dist/`, `build/`, or `vendor/` files for source changes.
- Run checks with `.venv\Scripts\python.exe -m unittest discover -s tests -v` on this Windows checkout. The suite includes FFmpeg integration tests; `python main.py --smoke-test` checks GUI startup.

## Known Codex sandbox limitation: TkinterDnD

- In the Codex Windows sandbox, `python main.py --smoke-test` may fail while constructing `TkinterDnD.Tk()` with `RuntimeError: Unable to load tkdnd library`, even when the project environment and release packaging are correct. Treat this as a known sandbox limitation once `.venv` contains `tkinterdnd2`, `tkinterdnd2/tkdnd/win-x64/libtkdnd2.10.2.dll` exists, and `build_windows.ps1` still uses `--collect-all tkinterdnd2`.
- When those conditions hold, do not spend time reinstalling `tkinterdnd2`, vendoring `tkdnd`, changing application code, or repeating the same diagnosis just to make the sandbox smoke test pass. Run the normal unit test suite and report the GUI smoke test as not verified in the sandbox.
- If GUI startup specifically needs verification, run `python main.py --smoke-test` in a normal desktop environment outside the Codex sandbox, or verify the packaged application. Investigate `tkdnd` as an application defect only if it also fails there.
