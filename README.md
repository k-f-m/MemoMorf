# MemoMorf

This project is a local desktop app for transcribing audio files on a CPU using CustomTkinter and faster-whisper.
It can render transcripts as raw segments, merged paragraphs, speaker-labeled turns, or speaker-labeled paragraphs.

## Prerequisites

- Python 3.10 or newer
- FFmpeg installed and available on your `PATH`

## Windows setup

Open PowerShell in this project folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install FFmpeg with `winget` if it is not already installed:

```powershell
winget install Gyan.FFmpeg
```

After installing FFmpeg, close and reopen PowerShell so the updated `PATH` is picked up.

## Run the app

```powershell
.\.venv\Scripts\Activate.ps1
python .\local_audio_transcriber.py
```

Downloaded Whisper models are stored in the local `.models` folder inside this project so the app remains self-contained.
The app also stores the last selected language, model size, speed profile, and window geometry in `.transcriber_settings.json`.
Speaker diarization downloads its own Hugging Face model cache on first use.

The UI includes a real percentage-based model download bar so first-time model downloads show byte progress instead of only a waiting state.
It also includes a dedicated Downloaded Models panel with per-model status and single-model deletion.
You can optionally transcribe only a selected section of the file by entering a start and end time, using clip preset buttons, adjusting a waveform-backed slider selector, or previewing the selected clip before transcription.

## Build a Windows executable

Install the packaging dependency:

```powershell
pip install -r requirements-dev.txt
```

Then build the app:

```powershell
.\build_windows_exe.ps1
```

The packaged app will be written to `dist\MemoMorf`.
The build script also applies an app icon and Windows version metadata to the executable.
Run `dist\MemoMorf\MemoMorf.exe` after packaging. Do not launch the intermediate executable from the `build` folder.

## Supported audio formats

- `.m4a`
- `.mp3`
- `.wav`
- `.aac`
- `.3gp`

## Notes

- The app runs locally on the CPU and does not require a GPU.
- The model is loaded with `compute_type="int8"` for CPU-friendly inference.
- Model downloads and cached models are stored in the local `.models` folder.
- Speaker-labeled views require access to the `pyannote/speaker-diarization-community-1` model.
- Before using speaker-labeled views, accept the Hugging Face model terms for `pyannote/speaker-diarization-community-1` and create an access token.
- Set that token in your shell before launching the app, for example `setx HF_TOKEN "your_token_here"` on Windows.
- This repository can be published under its own open-source license, but access to the speaker diarization model is governed separately by Hugging Face and `pyannote` model terms. Publishing this app does not grant redistribution rights for gated model weights or bypass model-access requirements.
- Speaker diarization is slower than plain transcription, especially on CPU.
- Active model downloads and transcriptions can be paused, resumed, or stopped from the main window.
- The Downloaded Models panel shows whether each supported model is downloaded, partial, or not downloaded, and lets you delete a selected model without clearing the whole cache.
- The `Clear Model Cache` button removes the local model cache and forces a fresh download the next time a model is used.
- The app warns on first launch if FFmpeg is missing and shows a guided Windows installation message.
- The cache clear action now asks for confirmation before deleting local models.
- `Standard` favors more stable segmentation, `Fast` uses lighter decoding, and `Ultra Fast` is the most aggressive speed preset.
- Clip ranges accept raw seconds, `mm:ss`, or `hh:mm:ss` values, and require both start and end times when entered manually.
- The app reads audio duration when you choose a file so the clip end can be picked more safely, waveform tooltips stay accurate while dragging, and presets such as `First 5 min`, `Last 5 min`, and `Current 30s` can be applied quickly.
- Clip preview uses `ffplay`, so the FFmpeg installation should include it on your `PATH`.
- If transcription fails on compressed audio formats, verify that FFmpeg is installed and on your `PATH`.

## Licensing

This repository includes an MIT `LICENSE` for the app source code.

Third-party packages used by this project remain under their own licenses. See `THIRD_PARTY_NOTICES.md` for a short summary.

The optional speaker diarization model `pyannote/speaker-diarization-community-1` is not redistributed by this repository. Access to that model, its gated download flow, and any related usage terms are governed separately by Hugging Face and `pyannote`.
