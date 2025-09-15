#!/usr/bin/env python3

"""
  diffalayze - a tool for automated binary diffing and LLM analysis

  by Moritz Abrell <moritz.abrell@syss.de>

  MIT License

  Copyright (c) 2025 SySS GmbH

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.
"""

__version__ = '1.0.0'
__author__ = 'Moritz Abrell'

import argparse
import importlib.util
import shutil
import subprocess
import threading
import time
import os
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

from tqdm import tqdm

APP_ROOT = Path(__file__).resolve().parent
TARGETS_DIR = (APP_ROOT / "targets").resolve()
SCRIPT_NAME = "fetch_target.py"
LLM_SCRIPT = (APP_ROOT / "utils" / "llmanalyze.py").resolve()

VERBOSE = False
LLM_VERBOSE = False
ANALYZE = False
ANALYZE_SLEEP = 0
PROGRESS_MODE = False

LLM_TRIGGER_CMD: Optional[str] = None
LLM_LEVEL_THRESHOLD = "HIGH"
LLM_BACKEND = "ollama"
LLM_MODEL: Optional[str] = None

GHIDRIFF_THREADS: int = 4
_ghidriff_sema: Optional[threading.Semaphore] = None

UID = os.getuid()
GID = os.getgid()

ghidriff_threads: List[Tuple[str, threading.Thread]] = []
analyze_threads: List[Tuple[str, threading.Thread]] = []
analyze_queue: List[Tuple[str, Path]] = []


def log(msg: str):
    if PROGRESS_MODE:
        tqdm.write(str(msg))
    else:
        print(str(msg))


def resolve_target_dir(name: str) -> Path:
    base = TARGETS_DIR 
    p = Path(name)
    t = p.resolve() if p.is_absolute() else (base / p).resolve()

    try:
        t.relative_to(base)
    except ValueError:
        raise ValueError(f"Target '{name}' is outside {base}")

    if not t.is_dir():
        raise FileNotFoundError(f"Target directory not found: {t}")

    return t


def monitor(pool, label: str):
    if not pool:
        return
    global PROGRESS_MODE
    VERBOSE and log(f"[*] Monitoring {label}")
    PROGRESS_MODE = True
    with tqdm(total=len(pool), desc=f"[*] {label}", unit="job", leave=True) as bar:
        done = set()
        while len(done) < len(pool):
            for n, th in pool:
                if not th.is_alive() and n not in done:
                    done.add(n)
                    bar.update(1)
            time.sleep(0.4)
    PROGRESS_MODE = False
    VERBOSE and print(f"[+] {label} complete")


def run_llmanalyze(target: str, archive: Path):
    sxs_dir = archive / "sxs_html"
    if not sxs_dir.is_dir():
        print(f"[!] {sxs_dir} missing - skipping LLM analysis")
        return

    out_file = archive / "analysis.md"
    cmd = [
        "python3",
        str(LLM_SCRIPT),
        "-i",
        str(sxs_dir),
        "-o",
        str(out_file),
        "--level-threshold",
        LLM_LEVEL_THRESHOLD,
        "--target-name",
        target,
        "--llm-backend",
        LLM_BACKEND,
    ]
    if LLM_MODEL:
        cmd += ["--llm-model", LLM_MODEL]
    if LLM_TRIGGER_CMD:
        cmd += ["--trigger-cmd", LLM_TRIGGER_CMD]
    if LLM_VERBOSE:
        cmd.append("-v")

    print(f"[*] Starting LLM analysis of {target}")
    subprocess.run(cmd, check=True)


def run_ghidriff_diff(t_dir: Path, old_f: Path, new_f: Path):
    target = t_dir.name
    diff_dir = t_dir / "ghidriffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    diff_dir.chmod(0o777)

    old_tar = diff_dir / old_f.name
    new_tar = diff_dir / new_f.name
    shutil.move(old_f, old_tar)
    shutil.move(new_f, new_tar)

    cmd = [
        "docker",
        "run",
        "--rm",
        "-u",
        f"{UID}:{GID}",
        "-e",
        "HOME=/tmp",
        "-e",
        "PYTHONPATH=/home/vscode/.local/lib/python3.12/site-packages",
        "-v",
        f"{diff_dir.resolve()}:/ghidriffs",
        "ghcr.io/clearbluejar/ghidriff:latest",
        "--force-diff",
        "--sxs",
        f"ghidriffs/{old_tar.name}",
        f"ghidriffs/{new_tar.name}",
    ]
    log(f"[*] Ghidriff ({target})")
    try:
        subprocess.run(
            cmd,
            stdout=None if VERBOSE else subprocess.DEVNULL,
            stderr=None if VERBOSE else subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        log(f"[!] Ghidriff failed ({target})")
        if not VERBOSE and e.stderr:
            try:
                log(e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr)
            except Exception:
                pass
        return

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    arch_dir = t_dir / "archive" / f"ghidriffs_{ts}"
    shutil.move(diff_dir, arch_dir)
    log(f"[+] Archived to {arch_dir}")

    if ANALYZE:
        analyze_queue.append((target, arch_dir))


def _ghidriff_worker(t_dir: Path, old_p: Path, new_p: Path):
    if _ghidriff_sema is None:
        run_ghidriff_diff(t_dir, old_p, new_p)
        return
    with _ghidriff_sema:
        run_ghidriff_diff(t_dir, old_p, new_p)


def load_and_run(target_name: str, force: bool):
    t_dir = resolve_target_dir(target_name)
    log(f"[*] Fetch script for {t_dir.name}")

    script = t_dir / SCRIPT_NAME
    v_log = t_dir / "version.log"
    if force and v_log.exists():
        v_log.unlink()

    if not script.is_file():
        log(f"[!] {SCRIPT_NAME} not found in {t_dir}")
        return

    spec = importlib.util.spec_from_file_location("fetch_target", str(script))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore

    if not hasattr(mod, "check_and_download"):
        log("[!] Script lacks check_and_download()")
        return

    res = mod.check_and_download()
    if isinstance(res, tuple) and len(res) == 2 and all(res):
        old_p, new_p = map(Path, res)
        th = threading.Thread(target=_ghidriff_worker, args=(t_dir, old_p, new_p))
        th.start()
        ghidriff_threads.append((t_dir.name, th))
    elif res is False:
        log("[*] No update.")
    else:
        log(f"[!] Unexpected result: {res}")


def parse_args():
    p = argparse.ArgumentParser(description="Patch diff automation with Ghidriff and LLMs")
    p.add_argument("target", help="Target name or 'all'")
    p.add_argument("-f", "--force", action="store_true",
                   help="Force download even if version unchanged")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Verbose output for diffalayze (docker, logging)")
    p.add_argument("-a", "--analyze", action="store_true",
                   help="Run llmanalyze.py on every newly archived diff")
    p.add_argument("-t", "--ghidriff-threads", type=int, default=4,
                   help="Max concurrent Ghidriff jobs (0 = unlimited)")
    p.add_argument("-lv", "--llm-verbose", action="store_true",
                   help="Pass -v to llmanalyze.py")
    p.add_argument("-ltc", "--llm-trigger-cmd", type=str, default=None,
                   help="Command to run if threshold met")
    p.add_argument("-llt", "--llm-level-threshold", type=str, default="HIGH",
                   choices=["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
                   help="Minimum level to trigger command")
    p.add_argument("-lb", "--llm-backend", type=str, default="ollama",
                   choices=["ollama", "openai", "anthropic"],
                   help="LLM backend API to be used")
    p.add_argument("-lm", "--llm-model", type=str,
                   help="LLM model to be used e.g. o4-mini")
    p.add_argument("-ls", "--llm-sleep", type=int, default=0,
                   help="Seconds to sleep between llmanalyze runs")
    return p.parse_args()


def banner():
    print(f"diffalayze v{__version__} by Moritz Abrell - SySS GmbH (c) 2025\n")


if __name__ == "__main__":
    banner()
    args = parse_args()

    VERBOSE = args.verbose
    LLM_VERBOSE = args.llm_verbose
    ANALYZE = args.analyze
    ANALYZE_SLEEP = args.llm_sleep
    LLM_TRIGGER_CMD = args.llm_trigger_cmd
    LLM_LEVEL_THRESHOLD = args.llm_level_threshold
    LLM_BACKEND = args.llm_backend
    LLM_MODEL = args.llm_model
    GHIDRIFF_THREADS = max(0, int(args.ghidriff_threads))
    _ghidriff_sema = None if GHIDRIFF_THREADS == 0 else threading.Semaphore(GHIDRIFF_THREADS)

    if args.target == "all":
        if not TARGETS_DIR.is_dir():
            raise FileNotFoundError(f"Targets-Verzeichnis fehlt: {TARGETS_DIR}")
        for d in TARGETS_DIR.iterdir():
            if d.is_dir():
                load_and_run(d.name, args.force)
    else:
        load_and_run(args.target, args.force)

    monitor(ghidriff_threads, "Ghidriff")

    if ANALYZE:
        for t, a in analyze_queue:
            run_llmanalyze(t, a)
            if ANALYZE_SLEEP:
                time.sleep(ANALYZE_SLEEP)

