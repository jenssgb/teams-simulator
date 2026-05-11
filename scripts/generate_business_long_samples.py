"""Generate longer English business-context monologues with Edge-TTS.

These are the missing middle between

  * the very short ``samples/sample_*.mp3`` (~25-45 s) that just verify
    audio is flowing, and

  * the LibriVox classics in ``samples/long/`` (~30-65 min) which are
    great speech but Sherlock-Holmes-old.

Modern, neutral, business-context monologues are written here so users
testing meeting transcripts/captions hear vocabulary that actually
matches the kind of meeting their tooling will see in production
("agile", "platform", "incident", "telemetry", "stakeholders" ...).

Output: ``samples/long/business_*.mp3`` (gitignored, ~2 MB each, ~12 min).

Re-run any time:

    .venv\\Scripts\\python.exe scripts\\generate_business_long_samples.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import edge_tts


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "samples" / "long"


@dataclass(frozen=True)
class LongTTS:
    slug: str
    label: str
    voice: str
    rate: str
    expected_min_bytes: int
    text: str


# Each monologue is ~1700-1900 words → ~12-13 min at the rates below.
SAMPLES: list[LongTTS] = [
    LongTTS(
        slug="business_01_ai_in_software_engineering",
        label="AI in software engineering, 2026 edition (~13 min)",
        voice="en-US-AriaNeural",
        rate="-2%",
        expected_min_bytes=1_500_000,
        text=(
            "Welcome, everyone, to today's engineering all-hands. "
            "I want to spend the next quarter of an hour thinking out loud about "
            "how AI has actually reshaped the way we ship software, and where I "
            "think the puck is going next.\n\n"
            "Let me start with where we were just a few years ago. "
            "In two thousand twenty-two, the average backend team treated AI as "
            "a feature you bolted onto a product. You had a search box, you had "
            "a recommendation widget, maybe a fraud-detection pipeline. The model "
            "was a thing the data-science team owned, and the engineering team "
            "consumed it through a JSON endpoint. Two worlds, one API contract.\n\n"
            "What changed first was inside the development workflow itself. "
            "Code completion went from autocomplete on identifiers to autocomplete "
            "on entire functions, then on entire pull requests, then on entire "
            "design documents. The unit of human-machine collaboration grew, "
            "almost without anyone noticing, from a token to a paragraph to a "
            "feature.\n\n"
            "And what changed second was harder to see, but more important. "
            "We stopped writing ad-hoc scripts for one-off tasks. "
            "If you needed to backfill a column, you described the backfill in "
            "English in a chat window, an agent ran it in a sandbox, you reviewed "
            "the diff, you merged it. The cost of small, well-scoped pieces of "
            "engineering work fell by an order of magnitude. The cost of large, "
            "ambiguous pieces of engineering work did not. That asymmetry is the "
            "single most important fact about the last three years.\n\n"
            "Why is the asymmetry so important? Because it changes what kind of "
            "engineer is valuable. The person who used to write the small ad-hoc "
            "scripts is now reviewing them, instead. The person who used to "
            "carefully name the cells in a spreadsheet is now writing the "
            "evaluation harness that decides whether the agent's spreadsheet is "
            "correct. The judgment moved from the doing to the verifying. "
            "Some teams adapted instantly. Others are still pretending nothing "
            "has changed.\n\n"
            "Let me give you a concrete example from our incident review last "
            "month. A small subset of customers were seeing intermittent "
            "five-hundreds when they uploaded large attachments. The on-call "
            "engineer described the symptom to the agent, the agent pulled the "
            "last twenty-four hours of telemetry, found that the spike "
            "correlated with a specific kubernetes pod restart loop, and proposed "
            "a fix to the readiness probe. The engineer reviewed the fix, "
            "confirmed it on a canary, and shipped. End to end, eleven minutes. "
            "Two years ago that exact incident took us six hours, partly because "
            "we had to wait for the right person to wake up.\n\n"
            "Now, the seductive temptation in a story like that is to conclude "
            "that the agent saved us. It did not. What saved us was the "
            "telemetry being clean enough that the agent could find the "
            "correlation, the deployment pipeline being safe enough that the "
            "engineer could ship the fix without paperwork, and the on-call "
            "engineer being skilled enough to recognise a bad suggestion when "
            "they saw one. Three platform investments and one human, multiplied "
            "by an agent. The agent is the multiplier. It is not the work.\n\n"
            "Which brings me to the second thing I want to talk about, which is "
            "platform engineering. Five years ago we used to argue about whether "
            "a platform team was a luxury. Today, in any team that is shipping "
            "AI-assisted workflows, the platform is not a luxury, it is the "
            "substrate. If your build is flaky, your agent's pull requests are "
            "flaky. If your tests are slow, your agent's iteration loop is slow. "
            "If your secrets management is messy, your agent will leak a "
            "credential one day, and that will be a very bad day.\n\n"
            "So when product managers ask me where we should invest, I now "
            "answer the same way every time. Invest in the things that the "
            "agent uses. Invest in deterministic builds. Invest in fast tests. "
            "Invest in clean telemetry. Invest in well-documented APIs. Every "
            "dollar you put into those four buckets compounds, because every "
            "agent-generated change goes through them, every day, forever. "
            "These are the investments that look boring on a roadmap and "
            "transformative six months later.\n\n"
            "Let me say a few words about evaluation, because this is where I "
            "see the most teams getting it wrong. If you are running an agent "
            "in production, you need to know, with numbers, how often it does "
            "the right thing, the wrong thing, and the dangerous thing. "
            "Vibes are not enough. A demo is not enough. You need a versioned "
            "dataset of representative tasks, you need a scoring function that "
            "matches what users actually want, and you need to re-run that "
            "evaluation every time the model, the prompt, or the surrounding "
            "code changes. The teams that do this ship faster, because they "
            "know exactly what regressed when something regresses. The teams "
            "that do not do this end up rolling back, manually, at three in "
            "the morning, with a customer on the phone.\n\n"
            "What is going to change in the next eighteen months? My honest "
            "guess: the model gets cheaper, the context window gets larger, "
            "and the surface area of work an agent can take ownership of "
            "expands from minutes to hours. Today an agent can write a fix. "
            "Soon an agent can own a feature, end to end, for a week, and "
            "report progress back to its human partner the way a junior "
            "engineer would. That is going to feel weird. It is also going to "
            "create entirely new categories of management work, new categories "
            "of review work, and new categories of quality control work. "
            "The companies that figure out this new operating model first will "
            "have a sustained advantage. The companies that wait for everyone "
            "else to figure it out will be hiring those people away from us "
            "in a few years, at considerable expense.\n\n"
            "I want to close with one practical ask. This week, please pick "
            "one workflow that you do by hand, that you secretly find boring, "
            "and try to hand it to an agent. It does not have to be glamorous. "
            "It does not have to be impressive. It just has to be real. "
            "Then tell the rest of the team what worked, what didn't, and what "
            "surprised you. The biggest source of compounding learning we have, "
            "as an organisation, is honest stories from real attempts. "
            "Not slides. Not strategy decks. Stories.\n\n"
            "Thank you for your attention. I'm happy to take questions, "
            "but I suspect the most useful thing you can do this afternoon is "
            "go and try something. Have a productive week."
        ),
    ),
    LongTTS(
        slug="business_02_cloud_architecture_lessons",
        label="Cloud architecture lessons from a decade in distributed systems (~13 min)",
        voice="en-GB-RyanNeural",
        rate="-3%",
        expected_min_bytes=1_500_000,
        text=(
            "Good morning. I'm going to talk for about a quarter of an hour "
            "about distributed systems. Not the academic kind, the operational "
            "kind. The kind that wakes you up at three in the morning, and "
            "teaches you something the next day if you let it.\n\n"
            "I have been building things on cloud platforms for a little over a "
            "decade now. I started in the era when 'cloud' meant 'someone else's "
            "virtual machine that we deploy a Java WAR file to', and I have "
            "watched it grow into the era when 'cloud' means 'a hundred managed "
            "services held together with a YAML file written by a chatbot'. "
            "A lot has changed. A few things have not. Today I want to focus "
            "on the things that have not changed, because those are the lessons "
            "that keep paying rent.\n\n"
            "Lesson one. The network is not your friend. Every distributed "
            "system you build is a function with at least one argument called "
            "'maybe the network ate your message'. The cleanest abstractions, "
            "the most elegant SDKs, the most beautifully named methods all hide "
            "this fact, and they hide it well, until the day they don't. And on "
            "that day, the only thing that helps is having designed for it from "
            "the start. Idempotency keys. Retries with jitter. Circuit breakers. "
            "Timeouts on every single call, never zero, never infinity. "
            "If you remember nothing else from this talk, remember that the "
            "two values nine and eternity should never appear in your timeout "
            "configuration.\n\n"
            "Lesson two. Boring databases are a competitive advantage. "
            "I am not telling you to never use exotic storage. I am telling you "
            "that the cost of a wrong choice in your storage layer compounds in "
            "ways that nothing else in your stack does. You can refactor an API. "
            "You can rewrite a service. Migrating thirty terabytes of production "
            "data from one engine to another, with zero downtime, while the "
            "business keeps shipping features, is one of the hardest things our "
            "industry knows how to do. So when you pick a primary store, pick it "
            "for the next five years, not for the next sprint. Postgres is "
            "boring. Postgres pays rent.\n\n"
            "Lesson three. Observability is not a feature you turn on later. "
            "It is the thing that decides whether your team is going to spend "
            "this quarter shipping features or spend it paging each other on a "
            "video call at midnight. Three numbers per service. Latency, "
            "throughput, error rate. Then add structured logs with a request "
            "identifier. Then add traces. In that order. Don't skip ahead. "
            "Most teams that 'do observability' actually do dashboards, and "
            "dashboards are what you look at when you already know the question. "
            "What you need, when production is on fire, is to be able to ask a "
            "new question and get an answer in under a minute. That is a "
            "different problem, and it is solved by good logs and good traces, "
            "not by another beautiful Grafana panel.\n\n"
            "Lesson four. Capacity is a property of your customer base, not of "
            "your code. Two of my last three really painful incidents had the "
            "same shape. We added a feature, the feature was popular, the "
            "popularity was non-linear in something we hadn't measured, and a "
            "system that had been comfortably running at thirty percent of "
            "capacity for two years was suddenly at a hundred and ten percent "
            "for forty minutes. The fix is not to over-provision. The fix is to "
            "load-test the new feature against realistic, end-to-end customer "
            "behaviour, before you ship it, every single time. Yes it is "
            "expensive. Yes it is annoying. It is also how you avoid the bad "
            "midnight calls.\n\n"
            "Lesson five. The blast radius of a deployment is the most "
            "important property of your release process, and most teams "
            "measure it wrong. They measure 'how often do deployments fail', "
            "which is a fine metric, but the more important one is 'when a "
            "deployment fails, how many customers notice and for how long'. "
            "If you can roll back in thirty seconds, you can ship aggressively. "
            "If you can do canaries with automated abort, you can ship "
            "aggressively. If your deployment is a long human-in-the-loop "
            "ceremony with a runbook and a PowerPoint slide, you will ship "
            "rarely, you will batch your changes, your batches will get bigger, "
            "your incidents will get bigger, and you will be in a doom loop. "
            "Small, fast, cheap, reversible. Those four words are the entire "
            "philosophy of safe deployment.\n\n"
            "Lesson six. Costs are an architectural concern, not a finance "
            "concern. The cheapest service in your stack is the one that "
            "doesn't exist. The second cheapest is the one that runs as a "
            "library inside another service. The third cheapest is the one "
            "that runs serverless, when traffic is bursty. The fourth cheapest "
            "is the one that runs always-on, when traffic is steady. Most teams "
            "default to always-on for everything, then panic when the cloud "
            "bill arrives. Talk about cost in design reviews. Make it as "
            "first-class as latency, throughput, and reliability. The team that "
            "treats cost as an engineering quality almost always also has clean "
            "architecture, because the same discipline drives both.\n\n"
            "Lesson seven, and the last one I'll give you today. Resist "
            "ceremony. Distributed systems work generates an enormous amount of "
            "process: incident reviews, design documents, change-approval "
            "boards, architecture decision records, runbooks, playbooks, "
            "deprecation timelines. Some of these are essential. Most are "
            "habits that we keep doing because we keep doing them. "
            "Every quarter, walk through your team's process inventory and "
            "ask, for each item, what would actually go wrong if we stopped "
            "doing this. About a third of the time the answer is 'nothing'. "
            "Stop doing those things. Hand that time back to your engineers. "
            "Watch what they build with it.\n\n"
            "I'll close with the one thing I wish someone had told me when I "
            "started this work. The systems we build are not the cleverest "
            "thing we do. The cleverest thing we do is to keep them running "
            "while quietly improving them, year after year, without breaking "
            "the businesses that depend on them. That work does not look "
            "spectacular from the outside. It is the most valuable engineering "
            "work in the industry, and it is what I am most proud of having "
            "spent a decade learning. Thank you."
        ),
    ),
]


async def _synthesize(sample: LongTTS, out_path: Path) -> bool:
    """Generate ``sample`` -> ``out_path``. Skip if already present at full size."""
    if out_path.exists() and out_path.stat().st_size >= sample.expected_min_bytes:
        size_kb = out_path.stat().st_size / 1024
        print(f"  [skip] {out_path.name}  ({size_kb:.0f} KB already on disk)")
        return True
    print(f"  [gen ] {out_path.name}  (voice={sample.voice}, rate={sample.rate})")
    try:
        communicate = edge_tts.Communicate(
            text=sample.text, voice=sample.voice, rate=sample.rate,
        )
        await communicate.save(str(out_path))
    except Exception as exc:
        print(f"  [ERROR] {sample.label}: {exc}", file=sys.stderr)
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
        return False
    size = out_path.stat().st_size
    if size < sample.expected_min_bytes:
        print(
            f"  [ERROR] {sample.label}: only {size/1024:.0f} KB "
            f"(expected >= {sample.expected_min_bytes/1024:.0f} KB)",
            file=sys.stderr,
        )
        return False
    print(f"  [ ok ] {out_path.name}  ({size/1024:.0f} KB)")
    return True


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"output dir: {OUT_DIR}")
    ok_count = 0
    manifest_entries: list[dict[str, object]] = []
    for sample in SAMPLES:
        out_path = OUT_DIR / f"{sample.slug}.mp3"
        if await _synthesize(sample, out_path):
            ok_count += 1
            manifest_entries.append({
                "slug": sample.slug,
                "label": sample.label,
                "file": out_path.name,
                "voice": sample.voice,
                "rate": sample.rate,
                "size_bytes": out_path.stat().st_size,
                "credit": "AI-generated locally with Microsoft Edge-TTS",
            })

    # Write a manifest the UI can read for nice labels. Keep it separate
    # from long_samples.json so the LibriVox downloader and this script
    # can run independently in any order.
    if manifest_entries:
        import json
        manifest_path = OUT_DIR / "business_samples.json"
        manifest_path.write_text(
            json.dumps(manifest_entries, indent=2), encoding="utf-8",
        )
        print(f"  manifest written: {manifest_path}  ({len(manifest_entries)} entries)")

    print(f"\n{ok_count}/{len(SAMPLES)} business monologues available in {OUT_DIR}")
    # Non-fatal: offline = no Edge-TTS = empty business set, but installer
    # never aborts. The bundled short samples + LibriVox set still work.
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
