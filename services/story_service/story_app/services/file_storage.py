import os

import aiofiles
from story_app.core.config import settings


class FileStorageManager:
    """Manages saving, reading, and deleting narrative text files (.txt) on disk."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = base_dir or settings.STORAGE_DIR
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_path(self, story_id: int) -> str:
        return os.path.join(self.base_dir, f"story_{story_id}.txt")

    async def save_story_text(self, story_id: int, content: str) -> str:
        file_path = self._get_path(story_id)
        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(content)
        return file_path

    async def read_story_text(self, file_path: str) -> str | None:
        if not os.path.exists(file_path):
            return None
        async with aiofiles.open(file_path, encoding="utf-8") as f:
            content = await f.read()
            return str(content)

    async def delete_story_text(self, file_path: str) -> None:
        if os.path.exists(file_path):
            os.remove(file_path)
