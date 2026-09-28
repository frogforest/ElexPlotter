from typing import Any

import httpx
from story_app.core.config import settings
from story_app.core.exceptions import UpstreamServiceException


class LoreServiceClient:
    """HTTP client for communicating with Lore Service."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.LORE_SERVICE_URL).rstrip("/")

    async def check_consistency(
        self,
        requires: list[int],
        creates: list[int],
        character_ids: list[int],
    ) -> dict[str, Any]:
        """Calls Lore Service POST /api/v1/consistency/check."""
        url = f"{self.base_url}/api/v1/consistency/check"
        payload = {
            "requires": requires,
            "creates": creates,
            "participating_character_ids": character_ids,
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code != 200:
                    raise UpstreamServiceException(
                        "Lore Service",
                        f"Status {res.status_code}: {res.text}",
                    )
                return res.json()  # type: ignore[no-any-return]
        except httpx.RequestError as exc:
            # When Lore Service is unreachable or offline, we wrap as upstream exception
            raise UpstreamServiceException("Lore Service", f"Connection failed: {exc}") from exc
