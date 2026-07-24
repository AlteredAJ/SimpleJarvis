import yaml
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=None)
def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def get_business_info(config: dict) -> str:
    """Returns a formatted string of business info for the system prompt."""
    c = config
    hours = "\n".join(
        f"  {day}: {times}" for day, times in c.get("hours", {}).items()
    )
    services = "\n".join(
        f"  - {s['name']}: {s.get('duration', '?')} min, ${s.get('price', '?')}"
        for s in c.get("services", [])
    )
    staff = ", ".join(c.get("staff", [])) or "any available staff"
    return (
        f"Business: {c['name']}\n"
        f"Phone: {c.get('phone', 'N/A')}\n"
        f"Address: {c.get('address', 'N/A')}\n"
        f"Hours:\n{hours}\n"
        f"Services:\n{services}\n"
        f"Staff: {staff}\n"
        f"Notes: {c.get('notes', '')}"
    )
