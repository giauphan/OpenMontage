"""News selection and research generation using Codex CLI."""
from lib.codex_news_selector import CodexNewsSelector

class ClaudeNewsSelector(CodexNewsSelector):
    """Backwards-compatible alias for CodexNewsSelector."""
    def __init__(self, cli_path: str = "codex"):
        super().__init__(cli_path=cli_path)
