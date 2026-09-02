"""PASR: provenance-aware span recall context broker.

This package is the productised core extracted from the frozen ``researchv2`` study.
The M0 layer is pure logic with no ``torch`` / ``transformers`` dependency: candidate
generation, reciprocal-rank fusion, hard-budget packing, ordering, workspace-safe file
discovery, and deterministic evidence accounting.
"""

from __future__ import annotations

__version__ = "0.0.1"

__all__ = ["__version__"]
