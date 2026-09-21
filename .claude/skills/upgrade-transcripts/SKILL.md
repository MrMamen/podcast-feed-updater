---
name: upgrade-transcripts
description: Half-yearly check and upgrade of the GPU transcription stack (faster-whisper, CTranslate2, pyannote, NB-Whisper). Baseline test first, targeted upgrade, same test after, diff.
---

# Upgrade the transcription stack

Run this about twice a year, or when a transcription fails after a driver
or system change. Everything runs locally on the user's NVIDIA GPU in WSL;
never try to do this in a cloud session.

Work in `$SCRATCHPAD` (the session scratchpad) for audio, VTTs and logs.
Never write test output into `transcripts/` and never touch
`transcripts/speaker_profiles.npy` except with `--merge` on the user's
request.

## 1. Baseline before changing anything

1. Every episode mix lives locally under `/mnt/t/MrMamen/CD SPILL/<N> <title>/`
   (Windows `T:\MrMamen\CD SPILL\`). `asr_common.find_episode_audio(N)`
   picks the mix; use a recent episode whose guest has a profile. Do not
   download from Podbean.
2. Cut a 5-minute clip (skip the first minute of intro music) to 16 kHz
   mono WAV with PyAV via the project venv. `scripts/asr_common.load_audio`
   does the decoding.
3. Run the full pipeline and keep the log:
   ```
   uv run python scripts/transcribe.py $SCRATCHPAD/clip.wav -o $SCRATCHPAD/before.vtt \
     --episode-number <N> --profiles transcripts/speaker_profiles.npy
   ```
   Leave out `--speakers` unless you know the count; community-1 counts on
   its own. Note: Whisper realtime factor, diarization time, speakers
   found, profile similarities, and the `<v>` tag counts
   (`grep -o "<v [^>]*>" file.vtt | sort | uniq -c`).

Healthy numbers on the RTX 3060 (Sept 2026): Whisper ~9x realtime
sequential, ~18x with `--batched`; ~5x realtime end to end; known voices
match their profile at 0.85–0.95; other profiles stay below ~0.5.

## 2. See what is outdated

```
uv pip list --outdated
uv lock --dry-run --upgrade-package faster-whisper --upgrade-package ctranslate2 \
  --upgrade-package pyannote-audio --upgrade-package av --upgrade-package huggingface-hub
```

Then check upstream, in this order of value:
- pyannote: GitHub releases/CHANGELOG, and whether a newer pretrained
  pipeline than `speaker-diarization-community-1` exists on Hugging Face.
- faster-whisper and CTranslate2 changelogs (look for Whisper alignment /
  VAD fixes and for CUDA 13 wheels, see below).
- `huggingface.co/NbAiLab/models?search=whisper&sort=modified` for a new
  full-size NB-Whisper. Distilled/turbo betas are not for production
  transcripts. A new model needs a CTranslate2 conversion
  (`TheStigh/nb-whisper-large-ct2` is the current one).

## 3. Upgrade, targeted

Upgrade only the ASR packages by name (`uv lock --upgrade-package …` then
`uv sync`). Do not run a blanket `uv lock --upgrade`.

Leave **torch** alone unless there is a concrete reason. Why: CTranslate2
ships CUDA 12 wheels and torch ships CUDA 13, so `nvidia-*-cu12` and the
cu13 packages coexist in the venv; both `nvidia-cudnn-cu12` (pinned
`<9.21`) and `nvidia-cudnn-cu13` claim `nvidia/cudnn/lib`. It works today.
If CTranslate2 ever ships CUDA 13 wheels, the cu12 packages and the pin in
`pyproject.toml` can go, and `setup_cuda_paths()` in `scripts/asr_common.py`
can lose the cu12 directories.

After `uv sync`, verify the GPU is still visible to both libraries:
```
uv run python -c "import torch, ctranslate2; print(torch.cuda.is_available(), ctranslate2.get_cuda_device_count())"
```
(`uv run python` alone doesn't set LD_LIBRARY_PATH; if this prints
`True 0`, run it through a script that calls `setup_cuda_paths()`, or
export the four paths from that function first.)

## 4. Same test after

Rerun step 1.3 to `after.vtt`, then `diff before.vtt after.vtt`. Expected:
a few 20–40 ms timestamp jitters and the odd cue split moved. Not
expected: different speaker tags, missing passages, changed profile
similarities beyond ~0.01, or a slower realtime factor.

If a new diarization pipeline is being tried, also run with
`--diarization-model <old>` and compare. Profile matching prints a warning
and skips if the new pipeline's embedding dimension differs from the
profiles; then the profiles must be rebuilt with
`scripts/build_profiles_clean.py` before the switch.

## 5. Wrap up

- Update `transcripts/README.md` if defaults or flags changed.
- Commit as `Claude <claude@anthropic.com>`, deps separate from code, and
  ask before committing (see CLAUDE.md).
- Report the before/after table to the user.

## Known noise

- pyannote prints a long torchcodec/libavutil traceback at import because
  WSL has no system ffmpeg. Harmless: audio is decoded with PyAV. Filter
  it out of logs with `grep -v` rather than "fixing" it.
- `pipeline._embedding` is a private attribute but is the supported way
  to reach the embedding model in pyannote 4.x; check it still exists
  after a pyannote major bump.
