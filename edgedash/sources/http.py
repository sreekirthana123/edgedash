import time
import requests
from typing import Optional, Any


class SourceError(Exception):
    """Raised when a source fetch fails."""
    pass


def get_json(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 10,
) -> dict[str, Any]:
    """Fetch JSON from URL with proper header identification schemas."""
    
    # Send standardized browser identifiers to satisfy strict bot prevention guards
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    default_headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Connection": "keep-alive"
    }

    if headers:
        default_headers.update(headers)

    max_retries = 2
    backoff_base = 1  # seconds

    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                params=params,
                headers=default_headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout as e:
            if attempt == max_retries - 1:
                raise SourceError(f"Timeout fetching {url}: {e}") from e
            time.sleep(backoff_base * (2 ** attempt))

        except requests.exceptions.HTTPError as e:
            if attempt == max_retries - 1:
                raise SourceError(f"HTTP error fetching {url}: {e.response.status_code}") from e
            time.sleep(backoff_base * (2 ** attempt))

        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise SourceError(f"Request failed for {url}: {e}") from e
            time.sleep(backoff_base * (2 ** attempt))

        except (ValueError, requests.exceptions.JSONDecodeError) as e:
            if attempt == max_retries - 1:
                raise SourceError(f"Invalid JSON response from {url}: {e}") from e
            time.sleep(backoff_base * (2 ** attempt))

    raise SourceError(f"Failed to fetch {url} after {max_retries} retries")
