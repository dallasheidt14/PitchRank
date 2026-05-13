"""GEO baseline runner: ask 20 prompts across 4 LLM engines, save raw responses + brand-mention stats.

Outputs:
  .turbo/geo/responses/<engine>/<prompt_id>.json    (raw per-call payload)
  .turbo/geo/baseline-2026-05.md                    (human-readable summary)

Skips any engine whose API key is not set, so you can run incrementally.

Engines + grounding:
  - OpenAI gpt-4o-search-preview (built-in web search)
  - Anthropic claude-opus-4-7 with web_search tool
  - Perplexity sonar-pro (built-in search)
  - Google gemini-2.5-pro with google_search grounding
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
PROMPTS_FILE = ROOT / "prompts.json"
RESPONSES_DIR = ROOT / "responses"
OUTPUT_MD = ROOT / "baseline-2026-05.md"

# Load .env from C:/PitchRank/.env
ENV_FILE = ROOT.parent.parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class CallResult:
    engine: str
    prompt_id: str
    category: str
    prompt: str
    response_text: str = ""
    brand_mentioned: bool = False
    brand_first_position: Optional[int] = None  # char index of first brand mention
    competitors_mentioned: list[str] = field(default_factory=list)
    citation_urls: list[str] = field(default_factory=list)
    latency_ms: int = 0
    error: Optional[str] = None
    model: str = ""


def analyze(text: str, brand_terms: list[str], competitors: list[str]) -> dict[str, Any]:
    text_l = text.lower()
    brand_pos = None
    for term in brand_terms:
        idx = text_l.find(term.lower())
        if idx != -1 and (brand_pos is None or idx < brand_pos):
            brand_pos = idx
    comps_hit = [c for c in competitors if c.lower() in text_l]
    urls = re.findall(r"https?://[^\s)\]\>'\"]+", text)
    return {
        "brand_mentioned": brand_pos is not None,
        "brand_first_position": brand_pos,
        "competitors_mentioned": comps_hit,
        "citation_urls": list(dict.fromkeys(urls)),  # dedup, preserve order
    }


def call_openai(prompt: str) -> tuple[str, list[str], str]:
    """Returns (text, citation_urls, model_used). Uses gpt-4o-search-preview."""
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = "gpt-4o-search-preview"
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    msg = resp.choices[0].message
    text = msg.content or ""
    urls: list[str] = []
    annotations = getattr(msg, "annotations", None) or []
    for ann in annotations:
        ann_type = getattr(ann, "type", None)
        if ann_type == "url_citation":
            cite = getattr(ann, "url_citation", None)
            if cite and getattr(cite, "url", None):
                urls.append(cite.url)
    return text, urls, model


def call_anthropic(prompt: str) -> tuple[str, list[str], str]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = "claude-opus-4-7"
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": prompt}],
    )
    text_parts: list[str] = []
    urls: list[str] = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
            citations = getattr(block, "citations", None) or []
            for c in citations:
                url = getattr(c, "url", None)
                if url:
                    urls.append(url)
        elif btype == "web_search_tool_result":
            content = getattr(block, "content", None) or []
            for item in content:
                url = getattr(item, "url", None)
                if url:
                    urls.append(url)
    return "\n".join(text_parts), list(dict.fromkeys(urls)), model


def call_perplexity(prompt: str) -> tuple[str, list[str], str]:
    import urllib.request

    model = "sonar-pro"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.perplexity.ai/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"]["content"]
    urls = data.get("citations") or data.get("search_results") or []
    if urls and isinstance(urls[0], dict):
        urls = [u.get("url") for u in urls if u.get("url")]
    return text, urls, model


def call_gemini(prompt: str) -> tuple[str, list[str], str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"])
    model = "gemini-2.5-flash"
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        ),
    )
    text = resp.text or ""
    urls: list[str] = []
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        gm = getattr(cand, "grounding_metadata", None)
        if not gm:
            continue
        chunks = getattr(gm, "grounding_chunks", None) or []
        for ch in chunks:
            web = getattr(ch, "web", None)
            if web and getattr(web, "uri", None):
                urls.append(web.uri)
    return text, list(dict.fromkeys(urls)), model


ENGINES = [
    ("openai",      "OPENAI_API_KEY",      call_openai),
    ("anthropic",   "ANTHROPIC_API_KEY",   call_anthropic),
    ("perplexity",  "PERPLEXITY_API_KEY",  call_perplexity),
    ("gemini",      "GEMINI_API_KEY",      call_gemini),  # also accepts GOOGLE_API_KEY
]


def run() -> int:
    panel = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    prompts = panel["prompts"]
    brand_terms = panel["brand_terms"]
    competitors = panel["competitors"]

    active: list[tuple[str, Any]] = []
    for name, env_key, fn in ENGINES:
        if name == "gemini":
            if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                active.append((name, fn))
                continue
        if os.environ.get(env_key):
            active.append((name, fn))

    if not active:
        print("No LLM API keys configured. Set at least one of: "
              "OPENAI_API_KEY, ANTHROPIC_API_KEY, PERPLEXITY_API_KEY, GEMINI_API_KEY.",
              file=sys.stderr)
        return 1

    print(f"Active engines: {', '.join(n for n, _ in active)}")
    print(f"Prompts: {len(prompts)}")
    print(f"Total calls: {len(active) * len(prompts)}")

    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    results: list[CallResult] = []

    for engine_name, fn in active:
        engine_dir = RESPONSES_DIR / engine_name
        engine_dir.mkdir(exist_ok=True)
        for p in prompts:
            out_path = engine_dir / f"{p['id']}.json"
            if out_path.exists():
                # resume support — skip already-run prompts
                cached = json.loads(out_path.read_text(encoding="utf-8"))
                results.append(CallResult(**cached))
                print(f"  [cached] {engine_name}/{p['id']}")
                continue

            print(f"  [run]    {engine_name}/{p['id']}: {p['text'][:60]}...")
            t0 = time.time()
            result = CallResult(
                engine=engine_name,
                prompt_id=p["id"],
                category=p["category"],
                prompt=p["text"],
            )
            try:
                text, urls, model = fn(p["text"])
                analysis = analyze(text, brand_terms, competitors)
                result.response_text = text
                result.citation_urls = list(dict.fromkeys((urls or []) + analysis["citation_urls"]))
                result.brand_mentioned = analysis["brand_mentioned"]
                result.brand_first_position = analysis["brand_first_position"]
                result.competitors_mentioned = analysis["competitors_mentioned"]
                result.model = model
            except Exception as e:  # noqa: BLE001
                result.error = f"{type(e).__name__}: {e}"
                print(f"           ERROR: {result.error}", file=sys.stderr)
            result.latency_ms = int((time.time() - t0) * 1000)
            out_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
            results.append(result)
            time.sleep(1.0)  # gentle pacing

    write_summary(results, prompts, panel)
    return 0


def write_summary(results: list[CallResult], prompts: list[dict], panel: dict) -> None:
    engines = sorted({r.engine for r in results})
    by_key: dict[tuple[str, str], CallResult] = {(r.engine, r.prompt_id): r for r in results}

    lines: list[str] = []
    lines.append("# GEO Baseline — 2026-05-13")
    lines.append("")
    lines.append("Initial measurement of PitchRank visibility across AI search engines, ahead of the 4-month GEO playbook scorecard (Aug 31, 2026).")
    lines.append("")
    lines.append(f"- Prompts: **{len(prompts)}** ({', '.join(sorted({p['category'] for p in prompts}))})")
    lines.append(f"- Engines: **{', '.join(engines)}**")
    lines.append("- Raw per-call payloads: `.turbo/geo/responses/<engine>/<prompt_id>.json`")
    lines.append("")
    lines.append("## Brand mention rate")
    lines.append("")
    lines.append("| Engine | Prompts answered | Brand mentioned | Mention rate |")
    lines.append("|---|---|---|---|")
    for eng in engines:
        eng_results = [r for r in results if r.engine == eng and not r.error]
        mentioned = sum(1 for r in eng_results if r.brand_mentioned)
        total = len(eng_results)
        rate = f"{(mentioned / total * 100):.0f}%" if total else "—"
        lines.append(f"| {eng} | {total}/{len(prompts)} | {mentioned} | {rate} |")
    lines.append("")
    lines.append("## Mention rate by prompt category")
    lines.append("")
    cats = sorted({p["category"] for p in prompts})
    header = "| Engine | " + " | ".join(cats) + " |"
    sep = "|" + "|".join(["---"] * (len(cats) + 1)) + "|"
    lines.append(header)
    lines.append(sep)
    for eng in engines:
        row = [eng]
        for cat in cats:
            cat_prompts = [p for p in prompts if p["category"] == cat]
            cat_results = [by_key.get((eng, p["id"])) for p in cat_prompts]
            cat_results = [r for r in cat_results if r and not r.error]
            mentioned = sum(1 for r in cat_results if r.brand_mentioned)
            total = len(cat_results)
            row.append(f"{mentioned}/{total}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Per-prompt result matrix")
    lines.append("")
    header = "| Prompt | " + " | ".join(engines) + " |"
    sep = "|" + "|".join(["---"] * (len(engines) + 1)) + "|"
    lines.append(header)
    lines.append(sep)
    for p in prompts:
        cells = []
        for eng in engines:
            r = by_key.get((eng, p["id"]))
            if r is None:
                cells.append("—")
            elif r.error:
                cells.append("ERR")
            elif r.brand_mentioned:
                cells.append(f"✅ #{r.brand_first_position}")
            else:
                cells.append("❌")
        lines.append(f"| {p['id']}: {p['text'][:60]}{'...' if len(p['text']) > 60 else ''} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Competitor mention rate")
    lines.append("")
    all_comps = panel["competitors"]
    header = "| Engine | " + " | ".join(all_comps) + " |"
    sep = "|" + "|".join(["---"] * (len(all_comps) + 1)) + "|"
    lines.append(header)
    lines.append(sep)
    for eng in engines:
        row = [eng]
        eng_results = [r for r in results if r.engine == eng and not r.error]
        for comp in all_comps:
            hits = sum(1 for r in eng_results if comp in r.competitors_mentioned)
            row.append(str(hits))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Re-run this baseline at the end of each playbook month to track movement.")
    lines.append("- Compare brand-mention rate AND citation URL frequency; AI engines weight first-cited sources heavily.")
    lines.append("- A 0% baseline is normal for emerging brands — the goal is movement, not absolute rank.")

    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote summary: {OUTPUT_MD}")


if __name__ == "__main__":
    sys.exit(run())
