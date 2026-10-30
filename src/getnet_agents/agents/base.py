"""Base class shared by all agents."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from ..llm import LLM
from ..schemas import AgentMessage, AgentName, AgentResult

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


class BaseAgent(ABC):
    name: AgentName

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.system_prompt = load_prompt(self.name.value)
        self.log = logging.getLogger(f"agent.{self.name.value}")

    @abstractmethod
    def handle(self, msg: AgentMessage) -> AgentResult: ...
