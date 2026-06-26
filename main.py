from __future__ import annotations

from langbot_plugin.api.definition.plugin import BasePlugin

from skill_authoring.store import CandidateStore


class SkillAuthoringPlugin(BasePlugin):
    async def initialize(self) -> None:
        self.candidate_store = CandidateStore(self)

