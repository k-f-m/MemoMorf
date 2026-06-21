# MemoMorf

MemoMorf is a local-first desktop app for CPU-based transcription, clip selection, and speaker-aware transcript review.
It is built with CustomTkinter, faster-whisper, and optional pyannote speaker diarization.

![MemoMorf application screenshot](assets/memomorf-screenshot.png)

## Why MemoMorf

| Focus | What you get |
| --- | --- |
| Local workflow | Transcribe audio on your machine without a hosted transcription service. |
| CPU friendly | Uses `compute_type="int8"` for practical CPU inference. |
| Better control | Pause, resume, stop, preview clips, and transcribe only the range you need. |
| Reusable models | Keep downloaded models in a local `.models` cache and manage them from the UI. |
| Multiple transcript views | Review raw segments, paragraphs, speaker-labeled turns, or speaker-labeled paragraphs. |

## Feature Snapshot

- Local CPU transcription with persistent model downloads.
- Waveform-backed clip selection with manual times and quick presets.
- Live status updates and a real percentage-based download progress bar.
- Downloaded Models panel with per-model state and single-model deletion.
- Optional speaker diarization for speaker-labeled transcript views.
- Windows packaging flow for a standalone executable build.

## Workflow

```mermaid
flowchart LR
	A[Choose audio file] --> B[Set language, model, and speed]
	B --> C[Optionally trim to a clip range]
	C --> D[Run transcription locally]
	D --> E[Review raw or paragraph transcript]
	D --> F[Optionally run speaker diarization]
	F --> G[Review speaker-labeled output]
```

## Transcript Modes

- `Raw`: original segment-by-segment output.
- `Paragraphs`: merged text for easier reading.
- `Speaker-labeled`: diarized turns with speaker labels.
- `Speaker-labeled paragraphs`: grouped speaker-attributed paragraphs.

## Requirements

- Python 3.10 or newer.
- FFmpeg available on your `PATH`.
- Windows PowerShell if you want to use the packaged build script as-is.

## Quick Start

Open PowerShell in the project folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install FFmpeg if it is not already available:

```powershell
winget install Gyan.FFmpeg
```

After installing FFmpeg, reopen PowerShell so the updated `PATH` is picked up.

Launch the app:

```powershell
.\.venv\Scripts\Activate.ps1
python .\local_audio_transcriber.py
```

## Packaging

Install the packaging dependency:

```powershell
pip install -r requirements-dev.txt
```

Build the Windows app:

```powershell
.\build_windows_exe.ps1
```

The packaged app is written to `dist\MemoMorf`.
Run `dist\MemoMorf\MemoMorf.exe` after packaging.
Do not launch the intermediate executable from the `build` folder.

## Supported Audio Formats

- `.m4a`
- `.mp3`
- `.wav`
- `.aac`
- `.3gp`

## Storage And Caching

- Whisper models are stored in the local `.models` folder.
- UI settings are stored in `.transcriber_settings.json`.
- Speaker diarization downloads its own Hugging Face cache on first use.
- The `Clear Model Cache` action removes local model data and forces a fresh download later.

## Speaker Diarization

Speaker-labeled modes depend on `pyannote/speaker-diarization-community-1`.

Before using speaker-labeled output:

- Accept the Hugging Face model terms for `pyannote/speaker-diarization-community-1`.
- Create a Hugging Face access token.
- Set the token before launching the app, for example:

```powershell
setx HF_TOKEN "your_token_here"
```

Notes:

- Speaker diarization is slower than plain transcription, especially on CPU.
- This repository does not redistribute gated model weights.
- Publishing this app does not grant redistribution rights or bypass Hugging Face and pyannote access requirements.

## Usage Notes

- `Standard` is the safest speed preset, while `Fast` and `Ultra Fast` trade stability for speed.
- Clip ranges accept raw seconds, `mm:ss`, or `hh:mm:ss` values.
- Manual clip entry requires both a start and end time.
- Presets such as `First 5 min`, `Last 5 min`, and `Current 30s` are available for faster trimming.
- Clip preview uses `ffplay`, so your FFmpeg installation should include it.
- If transcription fails on compressed formats, verify that FFmpeg is installed and available on your `PATH`.

## License

This repository includes the MIT license for the app source code in `LICENSE`.

Third-party packages remain under their own licenses.
See `THIRD_PARTY_NOTICES.md` for a short summary.
