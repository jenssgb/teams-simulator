"""Generate three bundled English speech samples using Microsoft Edge TTS.

This produces ``samples/sample_1_*.mp3`` ... ``samples/sample_3_*.mp3``.

Edge TTS uses Microsoft's free public neural voices (the same engine that
powers ``edge://`` Read-Aloud). Network access is required at GENERATION
time only -- the resulting MP3 files are committed to the repo and ship
without any runtime network requirement.

Run from repo root:
    .venv\\Scripts\\python.exe scripts\\generate_speech_samples.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import edge_tts


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "samples"


@dataclass(frozen=True)
class Sample:
    slug: str
    voice: str
    rate: str
    title: str
    text: str


SAMPLES: list[Sample] = [
    Sample(
        slug="sample_1_welcome_guy",
        voice="en-US-GuyNeural",
        rate="-2%",
        title="Welcome - Guy (US, male)",
        text=(
            "Welcome to the Teams Simulator. "
            "You are listening to a bundled sample so you can verify, end to end, "
            "that the virtual microphone is working inside Microsoft Teams. "
            "If you can hear my voice on the other side of the call, "
            "your setup is complete and you are ready to start your demo. "
            "Have fun, and please remember: this is a synthetic voice, "
            "generated locally for testing purposes only."
        ),
    ),
    Sample(
        slug="sample_2_ted_talk_aria",
        voice="en-US-AriaNeural",
        rate="+0%",
        title="Why simulators matter - Aria (US, female)",
        text=(
            "Here is a thought. Every great product team eventually hits the same wall. "
            "You build a feature that depends on a meeting, "
            "and you cannot ship it, because you cannot test it, "
            "because you do not have a meeting handy. "
            "Simulators change that. "
            "A good simulator turns a fragile, human, twenty-minute test "
            "into a one-click, repeatable, confident workflow. "
            "It is not glamorous engineering. "
            "But it is the kind of engineering that lets the rest of your team move ten times faster. "
            "Build the simulator. Future you will thank you."
        ),
    ),
    Sample(
        slug="sample_3_storytelling_ryan",
        voice="en-GB-RyanNeural",
        rate="-3%",
        title="Storytelling - Ryan (UK, male)",
        text=(
            "When I was twelve, my father gave me a small notebook. "
            "He said, every time you learn something new, write it down. "
            "Not the answer, he insisted. The question. "
            "Years later, I understood what he meant. "
            "Answers age. They get replaced, refined, sometimes embarrassingly overturned. "
            "But a good question, written down at the right time, "
            "keeps its shape for decades. "
            "So if you are starting something today, do yourself a favour. "
            "Write the question down first. "
            "Then go and find the answer."
        ),
    ),
]


async def _synthesize(sample: Sample, out_path: Path) -> None:
    print(f"  generating {out_path.name}  (voice={sample.voice}, rate={sample.rate})")
    communicate = edge_tts.Communicate(text=sample.text, voice=sample.voice, rate=sample.rate)
    await communicate.save(str(out_path))


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"writing samples to {OUT_DIR}")
    for sample in SAMPLES:
        out_path = OUT_DIR / f"{sample.slug}.mp3"
        await _synthesize(sample, out_path)
        size_kb = out_path.stat().st_size / 1024
        print(f"    -> {size_kb:6.1f} KB   {sample.title}")
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
