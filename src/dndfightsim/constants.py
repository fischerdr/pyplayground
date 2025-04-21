"""Defines constants used throughout the simulation (weapons, armor, etc.)."""

from typing import Any, Dict, List

# Type Aliases - These might move to datatypes.py later, but needed here for now
WeaponDict = Dict[str, Any]  # e.g., {"name": str, "damage": Tuple[int, int]}
ArmorDict = Dict[str, Any]  # e.g., {"name": str, "ac_bonus": int}
SpellDict = Dict[str, Any]  # e.g., {"name": str, "damage"/"heal"/"ac_bonus": ..., "duration": int}
ItemDict = Dict[str, Any]  # e.g., {"name": str, "type": str, "heal"/"damage": ...}


# --- Constants ---

# Game Data
WEAPONS: List[WeaponDict] = [
    {"name": "Short Sword", "damage": (1, 8), "range_type": "melee", "range": 1.0},
    {"name": "Long Sword", "damage": (1, 10), "range_type": "melee", "range": 1.0},
    {"name": "Bow", "damage": (1, 10), "range_type": "ranged", "range": 10.0},
    {"name": "Dagger", "damage": (1, 5), "range_type": "melee", "range": 1.0},
]

ARMORS: List[ArmorDict] = [
    {"name": "Leather Armor", "ac_bonus": 1},
    {"name": "Chain Mail", "ac_bonus": 3},
    {"name": "Plate Armor", "ac_bonus": 5},
    {"name": "Cloth", "ac_bonus": 0},
]

OFFENSIVE_SPELLS: List[SpellDict] = [
    {"name": "Fireball", "damage": (5, 10)},
    {"name": "Lightning Bolt", "damage": (4, 8)},
]

DEFENSIVE_SPELLS: List[SpellDict] = [
    {"name": "Shield", "ac_bonus": 2, "duration": 3},
    {"name": "Healing Light", "heal": (3, 6)},
]

INITIAL_ITEMS: List[ItemDict] = [
    {"name": "Health Potion", "type": "healing", "heal": (5, 10)},
    {"name": "Fire Bomb", "type": "damage", "damage": (3, 8)},
    {"name": "Antidote", "type": "healing", "heal": (1, 4)},  # Was type healing, corrected
]
