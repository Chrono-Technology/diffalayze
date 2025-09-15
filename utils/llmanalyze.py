#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml
from html2md import convert_file
from pocketflow import Flow, Node

from llm_client import call_llm, call_llm_json


PROMPTS_YAML = Path("utils") / "prompts.yaml"
LEVELS = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

BACKEND = "ollama"
MODEL: str | None = None
TEMPERATURE = 0.7
VERBOSE = False


def level_ge(a: str, b: str) -> bool:
    try:
        return LEVELS.index(a.upper()) >= LEVELS.index(b.upper())
    except ValueError:
        return False


def load_prompts(path: Path) -> Dict[str, Dict[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "prompts" not in data:
        raise ValueError("Invalid prompts.yaml: missing 'prompts'")
    return data["prompts"]


class LoadMarkdown(Node):
    def __init__(self, input_dir: Path):
        super().__init__()
        self.input_dir = input_dir


    def prep(self, _shared):
        return sorted(self.input_dir.glob("*.md"))


    def exec(self, paths):
        out = []
        for p in paths:
            VERBOSE and print(f"[*] Converting {p.name}")
            out.append({"path": str(p), "markdown": convert_file(p)})
        return out


    def post(self, shared, _prep, res):
        shared["docs"] = res


class AnalyzeEachDoc(Node):
    def prep(self, shared):
        return shared["docs"], shared["prompts"]["per_doc"]


    def exec(self, data):
        docs, prompt = data
        results: List[Dict[str, str]] = []
        for d in docs:
            msg = [
                {"role": "system", "content": prompt.get("system", "")},
                {"role": "user", "content": f"{prompt.get('user','')}\n\n{d['markdown']}"},
            ]
            analysis = call_llm(msg, backend=BACKEND, model=MODEL, temperature=TEMPERATURE)
            results.append({"path": d["path"], "analysis": analysis})
        return results


    def post(self, shared, _prep, res):
        shared["doc_analyses"] = res


class FinalReport(Node):
    def prep(self, shared):
        return shared["doc_analyses"], shared["prompts"]["final_synthesis"]


    def exec(self, data):
        anns, prompt = data
        combined = "\n\n---\n\n".join(a["analysis"] for a in anns)
        msg = [
            {"role": "system", "content": prompt.get("system", "")},
            {"role": "user", "content": f"{prompt.get('user','')}\n\n{combined}"},
        ]
        return call_llm(msg, backend=BACKEND, model=MODEL, temperature=TEMPERATURE)


    def post(self, shared, _prep, res):
        shared["final"] = res


class EvaluateFinal(Node):
    def prep(self, shared):
        return shared["final"], shared["prompts"]["evaluation"]


    def exec(self, data):
        final_md, prompt = data
        msg = [
            {"role": "system", "content": prompt.get("system", "")},
            {"role": "user", "content": f"{prompt.get('user','')}\n\n{final_md}"},
        ]
        return call_llm_json(msg, backend=BACKEND, model=MODEL, temperature=TEMPERATURE)


    def post(self, shared, _prep, res):
        shared["evaluation"] = res


class TriggerTool(Node):
    def __init__(self, cmd: str | None, threshold: str, target: str):
        super().__init__()
        self.cmd = cmd
        self.threshold = threshold
        self.target = target


    def prep(self, shared):
        return self.cmd, self.threshold, self.target, shared.get("evaluation", {})


    def exec(self, data):
        cmd, threshold, target, evaluation = data
        if not cmd:
            VERBOSE and print("[*] No trigger command configured")
            return {"triggered": False}

        level = str(evaluation.get("level", "NONE"))
        if not level_ge(level, threshold):
            VERBOSE and print(f"[*] Threshold {threshold} not reached ({level})")
            return {"triggered": False}

        line = f"{target} {evaluation.get('security_score','N/A')} {level}\n".encode()
        proc = subprocess.run(
            shlex.split(cmd), input=line, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return {
            "triggered": True,
            "returncode": proc.returncode,
            "stdout": proc.stdout.decode(),
            "stderr": proc.stderr.decode(),
        }


    def post(self, shared, _prep, res):
        shared["trigger_result"] = res


def build_flow(inp: Path, trig_cmd: str | None, thr: str, tgt: str) -> Flow:
    a = LoadMarkdown(inp)
    b = AnalyzeEachDoc()
    c = FinalReport()
    d = EvaluateFinal()
    e = TriggerTool(trig_cmd, thr, tgt)
    a >> b >> c >> d >> e
    return Flow(start=a)


def main() -> None:
    p = argparse.ArgumentParser(description="Automated diff analysis via LLM workflow")
    p.add_argument("-i", "--input", type=Path, default=Path("input"),
                        help="Directory containing SXS files")
    p.add_argument("-o", "--output", type=Path, default=Path("output.md"),
                        help="File to write the consolidated report")
    p.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose output")
    p.add_argument("-lc", "--trigger-cmd", type=str, default=None,
                        help="Command to run if evaluation threshold is met")
    p.add_argument("-lt", "--level-threshold", type=str, default="HIGH",
                        choices=LEVELS, help="Minimum level to trigger command")
    p.add_argument("-tn", "--target-name", type=str, default="target",
                        help="Target name")
    p.add_argument("-lb", "--llm-backend", type=str, default="ollama",
                   choices=["ollama", "openai", "anthropic"],
                   help="LLM backend API to be used")
    p.add_argument("-lm", "--llm-model", type=str,
                   help="LLM model to be used e.g. o4-mini")

    args = p.parse_args()

    global VERBOSE, BACKEND, MODEL
    VERBOSE = args.verbose
    BACKEND = args.llm_backend
    MODEL = args.llm_model

    prompts = load_prompts(PROMPTS_YAML)
    shared: Dict[str, Any] = {"prompts": prompts}

    flow = build_flow(args.input, args.trigger_cmd, args.level_threshold, args.target_name)
    flow.run(shared=shared)

    report = shared["final"]
    evaln = shared.get("evaluation", {})
    appendix = (
        "\n\n---\n\n## Security Relevance Evaluation\n"
        f"**Level:** {evaln.get('level','UNKNOWN')}  \n"
        f"**Score:** {evaln.get('security_score','N/A')}  \n"
        f"**Summary:** {evaln.get('summary','')}\n\n"
    )
    args.output.write_text(report + appendix, encoding="utf-8")
    print(f"[+] Report written to {args.output}")
    VERBOSE and print(
        f"[+] Evaluation for {args.target_name}: "
        f"Score: {evaln.get('security_score', 'N/A')}, "
        f"Level: {evaln.get('level', 'UNKNOWN')}"
    )


if __name__ == "__main__":
    main()

