"""Port: document ingestion.

A :class:`DocumentParser` turns raw bytes (a PDF, an image, etc.) into plain
text plus light metadata. Concrete adapters live under
``clauseguard.adapters.ingestion``. Phase 1 ships a native-PDF parser; Phase 2
adds OCR and table-structure adapters behind this same interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class ParsedDocument(BaseModel):
    """Text and metadata extracted from a raw document."""

    text: str
    page_count: int
    source_ref: str


@runtime_checkable
class DocumentParser(Protocol):
    """Parse raw document bytes into text."""

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        """Parse ``content`` into a :class:`ParsedDocument`.

        Args:
            content: Raw document bytes.
            source_ref: A label identifying the source (filename/URI) used for
                citations downstream.

        Returns:
            The parsed document.

        Raises:
            UnsupportedDocumentError: If the format cannot be handled.
            DocumentParseError: If parsing fails.
        """
        ...
