"""Parser for Gemini CLI text output."""

from __future__ import annotations

from typing import Any

from .base import BaseParser, ParsedCLIResponse, ParserError


class GeminiTextParser(BaseParser):
    """Parse stdout produced by Gemini CLI."""

    name = "gemini_text"

    def parse(self, stdout: str, stderr: str) -> ParsedCLIResponse:
        if not stdout.strip():
            raise ParserError("Gemini CLI returned empty stdout")

        metadata: dict[str, Any] = {}
        if stderr and stderr.strip():
            metadata["stderr"] = stderr.strip()

        return ParsedCLIResponse(content=stdout.strip(), metadata=metadata)
