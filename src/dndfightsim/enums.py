"""Enumerations used throughout the DnD Fight Simulator."""

from enum import Enum


# Enums for better code clarity
class Action(Enum):
    """Represents the possible actions a character can take in combat."""

    ATTACK = "attack"
    MOVE = "move"
    DODGE = "dodge"
    PARRY = "parry"
    USE_ITEM = "use_item"


class Personality(Enum):
    """Represents the personality of a character."""

    AGGRESSIVE = "aggressive"
    CAUTIOUS = "cautious"
    TACTICAL = "tactical"


class ItemType(Enum):
    """Represents the type of an item."""

    HEALING = "healing"
    DAMAGE = "damage"
    UNKNOWN = "unknown"


class StatusEffect(Enum):
    """Represents a status effect on a character."""

    POISONED = "poisoned"
    STUNNED = "stunned"
    UNKNOWN = "unknown"


class CharacterClass(Enum):
    """Represents the class of a character."""

    WARRIOR = "Warrior"
    MAGE = "Mage"
    RANGER = "Ranger"
    ROGUE = "Rogue"
    BASE = "Character"


# --- New Grid/Tile System Definitions ---


class TerrainType(Enum):
    """Represents the type of terrain on a tile."""

    FLOOR = "floor"
    WALL = "wall"
    GRASS = "grass"
    TREE = "tree"
    WATER = "water"
    ROCK = "rock"
    RUBBLE = "rubble"
    CAVE_WALL = "cave_wall"
    CHASM = "chasm"
    BUILDING_INTERIOR = "building_interior"
    STREET = "street"
    DOOR = "door"


class CoverType(Enum):
    """Represents the type of cover provided by a tile."""

    NONE = 0
    HALF = 2  # AC bonus
    THREE_QUARTERS = 5  # AC bonus


class ObscurityType(Enum):
    """Represents the level of obscurity on a tile."""

    CLEAR = "clear"
    LIGHTLY_OBSCURED = "lightly_obscured"  # Disadvantage on perception/attacks
    HEAVILY_OBSCURED = "heavily_obscured"  # Effectively Blinded
