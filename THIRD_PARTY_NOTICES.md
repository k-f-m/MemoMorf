# Third-Party Notices

This project depends on third-party software that remains subject to its own
licenses.

Notable runtime dependencies used by this repository include:

- `customtkinter` — CC0-1.0
- `faster-whisper` — MIT
- `huggingface-hub` — Apache-2.0
- `numpy` — BSD-3-Clause and other permissive notices
- `PyAV` (`av`) — BSD-3-Clause
- `pyannote.audio` — MIT
- `torch` — BSD-3-Clause
- `torchaudio` — BSD-style license
- `torchcodec` — BSD-3-Clause
- `ctranslate2` — MIT
- `onnxruntime` — MIT
- `tokenizers` — Apache-2.0
- `tqdm` — MPL-2.0 and MIT

Development and packaging dependency:

- `PyInstaller` — GPL-2.0-or-later with the PyInstaller exception

Notes:

- This file is a short summary, not a substitute for upstream license texts.
- If you distribute this app, review the licenses of bundled dependencies and
  include any notices required by those upstream packages.
- Access to the optional diarization model
  `pyannote/speaker-diarization-community-1` is governed separately by Hugging
  Face and `pyannote` model terms and is not granted by this repository's MIT
  license.