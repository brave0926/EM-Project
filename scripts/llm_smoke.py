"""Try the real LLM (EM_LLM=anthropic) once and print latency and outcome per job.

Usage:
    python scripts/llm_smoke.py                          # 2 calls: one extraction, one rewrite (per language: --all-langs)
    python scripts/llm_smoke.py --chips http://127.0.0.1:8000
        # the 20 demo chips (EN/RU/ZH/KO) through a running server started with EM_LLM=anthropic;
        # prints severity, notices and done.llm per chip

Reads ANTHROPIC_API_KEY (and EM_LLM_MODEL) from the environment or .env; never prints the key.
Only the fixed demo texts are sent, never personal data. Exit 2 when no key is configured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.app.clients.llm_client import AnthropicLlm, set_llm_client  # noqa: E402
from backend.app.core.config import LLM_TIMEOUT_S, llm_model  # noqa: E402
from backend.app.core.env import load_env  # noqa: E402
from backend.app.models.enums import Language  # noqa: E402
from backend.app.services import advice_service, classifier_service, llm_service  # noqa: E402

# Same texts as the chips in frontend/index.html.
CHIPS: dict[Language, list[str]] = {
    Language.EN: ["Severe burn on my hand, near Chungju Station, 2 AM", "Deep cut, bleeding, Yeonsu-dong, 11 PM",
                  "Fever and headache near City Hall, 3 AM", "Chest pain, hard to breathe, near Chungju Station",
                  "Mild sore throat near Chungju Station"],
    Language.RU: ["Сильный ожог руки, у вокзала Чхунджу, 2 часа ночи", "Глубокий порез, кровь, Ёнсу-дон, 23:00",
                  "Температура и головная боль, у мэрии, 3 часа ночи", "Боль в груди, трудно дышать, у вокзала Чхунджу",
                  "Немного болит горло, у вокзала Чхунджу"],
    Language.ZH: ["手部严重烧伤,忠州站附近,凌晨2点", "深度割伤出血,莲水洞,晚上11点", "发烧头痛,市政府附近,凌晨3点",
                  "胸痛呼吸困难,忠州站附近", "轻微喉咙痛,忠州站附近"],
    Language.KO: ["손에 심한 화상, 충주역 근처, 새벽 2시", "깊은 상처, 출혈, 연수동, 밤 11시", "열과 두통, 시청 근처, 새벽 3시",
                  "가슴 통증, 호흡 곤란, 충주역 근처", "가벼운 인후통, 충주역 근처"],
}


async def jobs(languages: list[Language]) -> int:
    client = AnthropicLlm(api_key=os.environ["ANTHROPIC_API_KEY"], model=llm_model())
    set_llm_client(client)
    print(f"model {client.model}, budget {LLM_TIMEOUT_S * 1000:.0f} ms per job")
    bad = 0
    try:
        for lang in languages:
            query = CHIPS[lang][0]
            ctx, job = await llm_service.extract_context(query, lang)
            print(f"{lang.value} extract  {job.outcome.value:8} {job.ms} ms  -> {ctx.model_dump() if ctx else None}")
            triage = classifier_service.classify(query)
            template = advice_service.build_advice(lang, triage, [], [], [], [])
            required = advice_service.required_in_rewrite(template, lang, triage, [])
            text, job = await llm_service.rewrite_advice(template, lang, required)
            kept = "template" if text == template else f"rewrite ({len(text)} chars)"
            print(f"{lang.value} rewrite  {job.outcome.value:8} {job.ms} ms  -> {kept}")
            bad += job.outcome.value != "ok"
    finally:
        await client.aclose()
    return 1 if bad else 0


async def chips(url: str) -> int:
    rows = []
    async with httpx.AsyncClient(base_url=url, timeout=15) as http:
        for lang, texts in CHIPS.items():
            for i, text in enumerate(texts):
                response = await http.post("/api/triage/stream", json={"query": text})
                response.raise_for_status()
                events = {}
                for block in response.text.strip().split("\n\n"):
                    fields = dict(line.split(": ", 1) for line in block.splitlines())
                    events.setdefault(fields["event"], json.loads(fields["data"]))
                done = events["done"]
                rows.append((f"{lang.value}#{i + 1}", events["triage"]["severity"], done["llm"], done["total_ms"],
                             done["notices"], "context" in events))
    print(f"{'chip':6} {'sev':6} {'outcome':8} {'extract':>8} {'rewrite':>8} {'total':>6} ctx notices")
    for name, sev, llm, total, notices, ctx in rows:
        print(f"{name:6} {sev:6} {llm['outcome']:8} {str(llm['extract_ms']):>8} {str(llm['rewrite_ms']):>8} "
              f"{total:>6} {'y' if ctx else '-':3} {','.join(notices) or '-'}")
    if all(r[2]["outcome"] == "off" for r in rows):
        print("all outcomes off: start the server with EM_LLM=anthropic and ANTHROPIC_API_KEY")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chips", metavar="URL", help="run the demo chips through a running server")
    parser.add_argument("--all-langs", action="store_true", help="job test in EN, RU, ZH and KO")
    args = parser.parse_args()
    if args.chips:
        return asyncio.run(chips(args.chips))
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("ANTHROPIC_API_KEY is not set (environment or .env): real LLM run unverified")
        return 2
    return asyncio.run(jobs(list(Language) if args.all_langs else [Language.EN]))


if __name__ == "__main__":
    sys.exit(main())
