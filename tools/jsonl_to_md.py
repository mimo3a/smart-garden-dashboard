"""Wandelt ein Claude-Code-Sitzungsprotokoll (.jsonl) in lesbares Markdown um.

Aufruf: python tools/jsonl_to_md.py <eingabe.jsonl> <ausgabe.md>
"""
import json
import sys
import pathlib

src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out = [f"# Claude Code – {dst.stem} (Smart Garden Dashboard)\n"]

for raw in src.read_text(encoding="utf-8").splitlines():
    try:
        e = json.loads(raw)
    except json.JSONDecodeError:
        continue
    t = e.get("type")
    if t not in ("user", "assistant") or e.get("isMeta"):
        continue
    if e.get("isCompactSummary"):
        out.append("\n> *[Hier wurde der Kontext automatisch komprimiert]*\n")
        continue
    content = (e.get("message") or {}).get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
    texts, tools = [], []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and b.get("text", "").strip():
            texts.append(b["text"].strip())
        elif b.get("type") == "tool_use":
            inp = b.get("input") or {}
            detail = inp.get("file_path") or inp.get("command") or inp.get("pattern") or ""
            tools.append(f"- `{b.get('name')}` {str(detail)[:120]}")
    if t == "user":
        text = "\n\n".join(texts)
        if not text or text.startswith("<"):
            continue  # Tool-Ergebnisse und interne Meldungen überspringen
        out.append("\n---\n\n### Prompt\n\n" + text + "\n")
    else:
        if texts:
            out.append("\n**Claude:**\n\n" + "\n\n".join(texts) + "\n")
        if tools:
            out.append("\n".join(tools) + "\n")

dst.write_text("\n".join(out), encoding="utf-8")
print(f"OK: {dst} ({dst.stat().st_size // 1024} KB)")
