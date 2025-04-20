"""Custom data type aliases used in the simulation."""

from dataclasses import dataclass
from typing import Any, Dict, Tuple

# Type aliases for complex data structures
# Use tuples for fixed-size coordinate pairs
Coordinate = Tuple[int, int]

# Use dictionaries for flexible data structures
WeaponDict = Dict[str, Any]  # e.g., {"name": str, "damage": Tuple[int, int]}
ArmorDict = Dict[str, Any]  # e.g., {"name": str, "ac_bonus": int}
SpellDict = Dict[str, Any]  # e.g., {"name": str, "damage"/"heal"/"ac_bonus": ..., "duration": int}
ItemDict = Dict[str, Any]  # e.g., {"name": str, "type": str, "heal"/"damage": ...}
StatusEffectDict = Dict[str, Any]  # e.g., {"name": str, "duration": int}
HazardTuple = Tuple[int, int, int]  # (x, y, damage) - Likely obsolete with HazardInfo


@dataclass
class HazardInfo:
    """Holds information about a hazard on a tile."""

    damage: int
    type: str  # e.g., "fire", "acid", "fall", "spike"
    # Optional: save_dc: Optional[int] = None
    # Optional: save_type: Optional[AbilityScore] = None # Needs AbilityScore enum
