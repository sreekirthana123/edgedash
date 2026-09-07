from abc import ABC, abstractmethod
from typing import Callable

SOURCES: dict[str, type["Source"]] = {}


def register(cls: type["Source"]) -> type["Source"]:
    """Decorator to register a Source class."""
    SOURCES[cls.name] = cls
    return cls


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self, config) -> list[dict]:
        """Fetch and return normalized job listings.

        Each dict must have exactly: source, external_id, title, company,
        location, url, description, posted_at, raw.
        Missing values are None.
        """
        ...
