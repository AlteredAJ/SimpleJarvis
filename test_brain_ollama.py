"""
Quick manual smoke test for brain_ollama.chat() — no tools, pure conversation.
Run: python test_brain_ollama.py
"""

import sys

from brain_ollama import chat


def safe_print(*args):
    # Windows console defaults to cp1252, which can't encode emoji/unicode
    # the model may return. Re-encode with replacement so the smoke test
    # never crashes on console output alone.
    text = " ".join(str(a) for a in args)
    sys.stdout.buffer.write(text.encode(sys.stdout.encoding or "utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    messages = [{"role": "user", "content": "Hello, who are you?"}]
    response = chat(messages)

    safe_print("stop_reason:", response["stop_reason"])
    safe_print("content:", response["content"])

    text_parts = [b["text"] for b in response["content"] if b["type"] == "text"]
    reply = " ".join(text_parts).strip()
    safe_print("\n--- Reply ---")
    safe_print(reply)
