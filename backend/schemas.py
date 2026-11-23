"""Request models for the API (kept tiny: the compiler itself defines the responses)."""

from pydantic import BaseModel, Field

MAX_SOURCE_CHARS = 100_000


class SourceRequest(BaseModel):
    """Every compile endpoint takes just the program text."""

    source: str = Field(default="", max_length=MAX_SOURCE_CHARS,
                        description="NovaLang source code")
