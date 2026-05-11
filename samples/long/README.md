# Long monologue samples (downloaded on demand)

This folder is populated automatically by
[`scripts/download_long_samples.py`](../../scripts/download_long_samples.py),
which the Windows installer runs for you.

The files (~73 MB total) are public-domain LibriVox recordings, single
narrator, 30-65 minutes each — exactly the kind of input that exercises
Teams' transcript pipeline meaningfully.

To (re-)fetch manually:

```powershell
.venv\Scripts\python.exe scripts\download_long_samples.py
```

`*.mp3` and `long_samples.json` are gitignored — they live on disk only.
