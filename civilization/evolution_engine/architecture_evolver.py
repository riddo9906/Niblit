"""ArchitectureEvolver — evolves agent architecture configurations.

Usage example::

    evolver = ArchitectureEvolver()
    evolved = evolver.evolve({"layers": 4, "hidden_dim": 256}, {"accuracy": 0.8})
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

log = logging.getLogger("ArchitectureEvolver")

_IMPROVEMENTS: List[str] = [
    "add_residual_connections",
    "increase_hidden_dim",
    "add_attention_layer",
    "add_layer_norm",
    "reduce_dropout",
    "add_skip_connections",
]


class ArchitectureEvolver:
    """Proposes and applies improvements to agent architectures."""

    # ── public API ──

    def evolve(
        self,
        architecture: Dict[str, Any],
        performance_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return evolved architecture based on *performance_metrics*."""
        improvements = self.suggest_improvements(architecture)
        evolved = dict(architecture)
        for improvement in improvements[:2]:
            evolved = self.apply_improvement(evolved, improvement)
        log.info("ArchitectureEvolver: evolved architecture with %d improvements", len(improvements[:2]))
        return evolved

    def suggest_improvements(self, arch: Dict[str, Any]) -> List[str]:
        """Return list of suggested improvement names for *arch*."""
        suggestions = []
        if arch.get("layers", 0) < 6:
            suggestions.append("add_residual_connections")
        if arch.get("hidden_dim", 0) < 512:
            suggestions.append("increase_hidden_dim")
        if "attention" not in str(arch):
            suggestions.append("add_attention_layer")
        suggestions.extend(_IMPROVEMENTS[:3])
        return list(dict.fromkeys(suggestions))

    def apply_improvement(
        self, arch: Dict[str, Any], improvement: str
    ) -> Dict[str, Any]:
        """Apply *improvement* to *arch* and return updated dict."""
        updated = dict(arch)
        if improvement == "increase_hidden_dim":
            updated["hidden_dim"] = arch.get("hidden_dim", 128) * 2
        elif improvement == "add_attention_layer":
            updated["has_attention"] = True
        elif improvement == "add_residual_connections":
            updated["residual"] = True
        elif improvement == "add_layer_norm":
            updated["layer_norm"] = True
        elif improvement == "reduce_dropout":
            updated["dropout"] = max(0.0, arch.get("dropout", 0.3) - 0.1)
        return updated


if __name__ == "__main__":
    print('Running architecture_evolver.py')
