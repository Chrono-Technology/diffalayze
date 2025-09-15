# diffalayze – Automated Binary Diffing & LLM-Assisted Security Analysis

**diffalayze** is a versatile toolkit for automating *patch diffing* of binary targets and enriching the results with deep-dive analysis from large language models (LLMs).
It is designed for **reverse engineers**, **vulnerability researchers**, and **security teams** who need to track software changes, highlight potentially security-relevant modifications, and produce actionable insights quickly.


## What is diffalayze?

Check out the [blog post](https://blog.syss.com/posts/automated-patch-diff-analysis-using-llms/)!

`diffalayze` orchestrates the entire patch diffing workflow:

* **Fetches** old and new versions of a binary automatically
* **Runs** side-by-side diffs using [Ghidriff](https://github.com/clearbluejar/ghidriff) in Docker
* **Analyzes** results using an LLM pipeline with structured scoring and severity levels
* **Archives** every run for reproducibility and auditing

The result: fast, repeatable, and AI-enhanced binary patch analysis.


## Project Structure

```
┌─ diffalayze.py       → Main orchestration (CLI, Docker, Ghidriff, LLM)
│
├─ utils/
│   ├─ llm_client.py   → Backend-agnostic LLM helper (Ollama, OpenAI, Claude)
│   ├─ llmanalyze.py   → Pocketflow-based diff analysis pipeline
│   └─ prompts.yaml    → Prompt definitions for multi-stage LLM analysis
│
└─ targets/
    └─ <product-dir>/  → Target-specific directory (binaries, diffs, archives)
        └─ fetch_target.py  → Script to download, extract & compare versions
```


## Key Features

* **Automated Binary Diffing**
  Runs Ghidriff in a Docker container to produce detailed *side-by-side* (SxS) diffs.

* **LLM-Powered Security Analysis**
  Converts raw diffs into structured, severity-rated reports (`NONE` → `CRITICAL`).

* **Modular & Backend-Agnostic**
  Plug-and-play with OpenAI, Claude (Anthropic), or Ollama.

* **Trigger-Based Actions**
  Execute custom commands automatically when a severity threshold is met.

* **Versioned Archiving**
  Every run is timestamped and stored for future comparison and auditing.


## Installation

### 1. Ghidriff (Docker)

```bash
docker pull ghcr.io/clearbluejar/ghidriff:latest
```

You must have permission to run Docker containers (e.g., be a member of the `docker` group).

### 2. Python Dependencies

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 3. Optional Backends

```bash
pip install openai anthropic
```


## Defining a Target

A target lives in `targets/<product-name>/` and **must** include a `fetch_target.py` script that:

1. Downloads the **old** and **new** binary versions
2. Verifies if a new version is available
3. Outputs the **absolute paths** to both versions, e.g.:

   ```
   /home/user/diffalayze/targets/mrxsmb/old.mrxsmb.sys /home/user/diffalayze/targets/mrxsmb/new.mrxsmb.sys
   ```

**Tip:** For Windows binaries, you can use the provided Winbindex-based example in `targets/`.
Just adjust:

* `dbfile`
* `filename`
* `windows_version`

`diffalayze` supports **any architecture** Ghidra can handle – not just Windows binaries.


## Usage

### Show all CLI options

```bash
python3 diffalayze.py -h
```

### Diff + Analyze all targets

```bash
export OPENAI_API_KEY="sk-..."
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

python3 diffalayze.py all -f -a -lb openai -lm gpt-5
```

Reports are saved to:

```
targets/<target>/archive/ghidriffs_<timestamp>/analysis.md
```

### Diff + Analyze a single target

```bash
python3 diffalayze.py tdx-1607 -f -a -lb openai -lm gpt-5-nano -lv
```

### Diff only

```bash
python3 diffalayze.py tdx-1607 -f
```

### Analyze only (existing Ghidriff output)

```bash
python3 utils/llmanalyze.py -i <path-to-sxs-output> -v -lb ollama -tn TDX
```

### Trigger a custom action when severity threshold is met

```bash
python3 diffalayze.py tdx-1607 -f -a -llt MEDIUM -ltc ./notify.sh -lb openai -lm gpt-5-nano
```


## Environment Variables

| Variable            | Description                                         |
| ------------------- | --------------------------------------------------- |
| `OPENAI_API_KEY`    | API key for OpenAI                                  |
| `ANTHROPIC_API_KEY` | API key for Claude (Anthropic)                      |
| `OLLAMA_URL`        | Ollama endpoint (default: `http://localhost:11434`) |
| `SSL_CERT_FILE`     | CA certificate file path                            |


## LLM Prompt Stages

`prompts.yaml` defines three stages:

1. **`per_doc`** – Analyzes each diffed function in isolation
2. **`final_synthesis`** – Combines per-function insights into a full report
3. **`evaluation`** – Outputs a structured JSON with `level`, `score`, `summary`, and recommended actions

Easily customizable to match your **security policy** or **analysis style**.


## Notes & Best Practices

* **Token usage**
  Expect \~8K tokens per changed function + \~5K for the summary (varies by code size and model).

* **Human verification required**
  LLM results are **assistive**, not authoritative – always review findings manually.


## Credits

This project builds on the excellent work of:

* [Ghidra](https://ghidra-sre.org/)
* [Ghidriff](https://github.com/clearbluejar/ghidriff)
* [Pocketflow](https://github.com/The-Pocket/PocketFlow)
* [Winbindex](https://github.com/m417z/winbindex)


## Disclaimer

Use responsibly and only with permission from all relevant parties.
This toolkit is intended for **educational** and **research** purposes only.

