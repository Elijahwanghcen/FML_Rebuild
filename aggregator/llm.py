"""Thin cached wrapper around the local `claude` CLI for 'read it liberally' extraction steps.
Deterministic code does the fetching; the LLM only turns messy text into JSON. Every answer is cached."""
import hashlib, json, re, subprocess, tempfile
from pathlib import Path
from common import ROOT

CACHE = ROOT / "data" / "_llm_cache"


def ask_json(prompt, model="haiku", timeout=240):
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = CACHE / (hashlib.sha1((model + prompt).encode()).hexdigest()[:24] + ".json")
    if cp.exists():
        return json.loads(cp.read_text())
    full = prompt + "\n\nRespond with ONLY valid JSON. No prose, no code fences."
    try:
        r = subprocess.run(["claude", "-p", "--model", model], input=full, capture_output=True,
                           text=True, timeout=timeout, cwd=tempfile.gettempdir())
    except subprocess.TimeoutExpired:
        return None
    txt = r.stdout.strip()
    m = re.search(r"(\[.*\]|\{.*\})", txt, re.S)
    try:
        out = json.loads(m.group(1)) if m else None
    except Exception:
        out = None
    if out is not None:
        cp.write_text(json.dumps(out))
    return out
