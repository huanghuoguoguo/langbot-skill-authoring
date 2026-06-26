from __future__ import annotations

import json
from typing import Any

from .models import SkillCandidate


class CandidateStore:
    KEY = "skill_authoring_candidates_v1"

    def __init__(self, plugin: Any | None = None) -> None:
        self.plugin = plugin
        self._memory: dict[str, dict[str, Any]] = {}

    async def list(self) -> list[SkillCandidate]:
        data = await self._load()
        candidates = [SkillCandidate.from_dict(item) for item in data.values()]
        candidates.sort(key=lambda item: item.updated_at, reverse=True)
        return candidates

    async def get(self, candidate_id: str) -> SkillCandidate | None:
        data = await self._load()
        item = data.get(candidate_id)
        return SkillCandidate.from_dict(item) if item else None

    async def save(self, candidate: SkillCandidate) -> SkillCandidate:
        data = await self._load()
        data[candidate.id] = candidate.to_dict()
        await self._save(data)
        return candidate

    async def _load(self) -> dict[str, dict[str, Any]]:
        if self.plugin is None:
            return dict(self._memory)
        try:
            raw = await self.plugin.get_plugin_storage(self.KEY)
        except Exception:
            return dict(self._memory)
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        if not isinstance(decoded, dict):
            return {}
        return {str(key): value for key, value in decoded.items() if isinstance(value, dict)}

    async def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self._memory = dict(data)
        if self.plugin is None:
            return
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            await self.plugin.set_plugin_storage(self.KEY, payload)
        except Exception:
            return

