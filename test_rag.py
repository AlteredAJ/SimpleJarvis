"""
test_rag.py — manual sanity check for rag.py against the real wiki vault.

Not a pytest suite (no vault fixtures) — just runs a few real queries
verified against actual page content and prints the results so a human
can eyeball whether the ranking makes sense. Read-only against the vault.
"""

import sys

from rag import get_context, _vault_path, _load_pages

# Windows consoles default to cp1252, which chokes on em-dashes ("—") that
# are all over the vault's page titles. Reconfigure stdout to UTF-8 so the
# test output doesn't crash on print().
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def run_query(label: str, query: str, **kwargs) -> None:
    banner(f"QUERY: {label!r} -> {query!r}")
    result = get_context(query, **kwargs)
    if not result:
        print("(empty — no page scored above zero)")
        return
    print(f"[{len(result)} chars total]\n")
    print(result)


def main() -> None:
    vault = _vault_path()
    pages = _load_pages(vault)
    print(f"Vault path: {vault}")
    print(f"Loaded {len(pages)} pages.")
    print("Sample titles:", list(pages.keys())[:8])

    # Query 1 — verified against Now.md / Summer 2 2026 Academics.md content:
    # PHYS 226 is explicitly mentioned as the current academic focus.
    run_query(
        "PHYS 226 physics class",
        "What's going on with my PHYS 226 class right now?",
    )

    # Query 2 — verified against BLE Reverse Engineering — Tesla ProtectBattery.md
    # title and the [[BLE Reverse Engineering — Tesla ProtectBattery]] link in
    # both Now.md and index.md.
    run_query(
        "Tesla BLE reverse engineering",
        "Tell me about the Tesla ProtectBattery BLE reverse engineering project",
    )

    # Query 3 — verified against DualSense Haptics pages (DualSense Mac Setup.md,
    # Universal DualSense Haptics — Project.md, DualSense Haptics — Update
    # Pipeline.md all exist and cross-reference each other).
    run_query(
        "DualSense haptics project",
        "What's the status of the DualSense haptics project and its update pipeline?",
    )

    # Query 4 — nonsense query with no real overlap in the vault; should come
    # back empty rather than force in irrelevant pages.
    run_query(
        "nonsense / no match",
        "purple elephant quantum banana soufflé recipe",
    )


if __name__ == "__main__":
    main()
