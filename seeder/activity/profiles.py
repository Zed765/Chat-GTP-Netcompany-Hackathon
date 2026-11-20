"""How each team of the demo organisation uses AI tools: which tools, how much, and what
its people paste into them. The seeded logs and prompts are drawn from these profiles."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

Kind = Literal["benign", "client", "personal", "contract", "marked", "secret"]

# The team that joined the gateway late: its prompts stayed unmasked for longer.
LATE_TEAM = "Customer Support"
DEMO_TOOLS = ("athena-assist", "draftpilot", "chatterbox-ai")


@dataclass(frozen=True)
class Tool:
    slug: str
    status: str
    domains: tuple[str, ...]


@dataclass(frozen=True)
class TeamProfile:
    prompts: int
    kinds: Mapping[Kind, float]
    tools: Mapping[str, float]


PROFILES: dict[str, TeamProfile] = {
    "Sales": TeamProfile(
        prompts=520,
        kinds={"benign": 0.45, "client": 0.38, "contract": 0.05, "marked": 0.07, "personal": 0.05},
        tools={"chatterbox-ai": 5, "chatgpt": 3, "draftpilot": 2, "grammarly": 1,
               "athena-assist": 3, "deepl": 1},
    ),
    "Customer Support": TeamProfile(
        prompts=420,
        kinds={"benign": 0.50, "client": 0.35, "personal": 0.10, "marked": 0.05},
        tools={"chatterbox-ai": 3, "chatgpt": 2, "quillbot": 1, "draftpilot": 2,
               "athena-assist": 4, "deepl": 2},
    ),
    "Engineering": TeamProfile(
        prompts=440,
        kinds={"benign": 0.72, "secret": 0.12, "client": 0.04, "marked": 0.06, "personal": 0.06},
        tools={"github-copilot": 5, "athena-assist": 2, "claude": 2, "openai-api": 1,
               "cursor": 3, "chatgpt": 2, "deepseek": 1},
    ),
    "Finance": TeamProfile(
        prompts=260,
        kinds={"benign": 0.45, "client": 0.25, "marked": 0.20, "personal": 0.10},
        tools={"athena-assist": 4, "microsoft-365-copilot": 2, "draftpilot": 2,
               "perplexity": 2, "chatgpt": 1},
    ),
    "Legal": TeamProfile(
        prompts=180,
        kinds={"benign": 0.40, "contract": 0.30, "client": 0.15, "marked": 0.15},
        tools={"athena-assist": 5, "deepl": 1, "draftpilot": 2, "chatterbox-ai": 1,
               "perplexity": 1},
    ),
    "HR": TeamProfile(
        prompts=180,
        kinds={"benign": 0.50, "personal": 0.30, "marked": 0.20},
        tools={"athena-assist": 4, "microsoft-365-copilot": 1, "grammarly": 2, "draftpilot": 1,
               "quillbot": 1, "otter-ai": 1},
    ),
}  # fmt: skip


def allocate[K](total: int, weights: Mapping[K, float]) -> list[K]:
    """Split `total` by weight with the largest-remainder method, so counts are exact."""
    scale = total / sum(weights.values())
    shares = {key: weight * scale for key, weight in weights.items()}
    counts = {key: int(share) for key, share in shares.items()}
    by_remainder = sorted(shares, key=lambda key: shares[key] - counts[key], reverse=True)
    for key in by_remainder[: total - sum(counts.values())]:
        counts[key] += 1
    return [key for key, count in counts.items() for _ in range(count)]


def team_tools(team: str, inventory: Sequence[Tool]) -> dict[Tool, float]:
    """The team's tools that the inventory knows, or the fictional ones if it knows none."""
    known = {tool.slug: tool for tool in inventory}
    weights = {
        known[slug]: weight for slug, weight in PROFILES[team].tools.items() if slug in known
    }
    return weights or {known[slug]: 1.0 for slug in DEMO_TOOLS if slug in known}
