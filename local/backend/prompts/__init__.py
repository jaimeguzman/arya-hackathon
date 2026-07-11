# ponytail: plain file load — ceiling: no caching/templating; upgrade: add Jinja if Phase 5 needs it
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(stem: str) -> str:
    """Load `backend/prompts/{stem}.txt` as UTF-8 text."""
    path = _PROMPTS_DIR / f"{stem}.txt"
    return path.read_text(encoding="utf-8")
