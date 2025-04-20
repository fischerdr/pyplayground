from dataclasses import dataclass  # Keep dataclass import if Tile uses it, otherwise remove

# Assuming Character will be defined elsewhere, need forward reference or import later
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .characters.base import Character  # Example relative import path

from .datatypes import HazardInfo
from .enums import CoverType, ObscurityType, TerrainType


class Tile:
    """Represents a single square on the battle grid."""

    def __init__(self, terrain_type: TerrainType = TerrainType.FLOOR, x: int = 0, y: int = 0):
        """Initializes a Tile based on its terrain type."""
        self.x: int = x
        self.y: int = y
        self.terrain_type: TerrainType = terrain_type
        self.character: Optional["Character"] = None
        self.hazard: Optional[HazardInfo] = None
        self.provides_cover: CoverType = CoverType.NONE
        self.blocks_movement: bool = False
        self.blocks_los: bool = False
        self.movement_cost: int = 1
        self.obscurity: ObscurityType = ObscurityType.CLEAR
        self.display_char: str = "."  # Default floor

        self._set_properties_from_terrain()
        self.update_display_char()  # Initial display char based on terrain

    # flake8: noqa: C901 - Function is too complex
    def _set_properties_from_terrain(self) -> None:
        """Sets tile properties based on the terrain type."""
        if self.terrain_type == TerrainType.FLOOR:
            self.display_char = "."
            self.blocks_movement = False
            self.blocks_los = False
            self.provides_cover = CoverType.NONE
            self.movement_cost = 1
        elif self.terrain_type == TerrainType.WALL:
            self.display_char = "#"
            self.blocks_movement = True
            self.blocks_los = True
            self.provides_cover = CoverType.NONE  # Walls block movement entirely
            self.movement_cost = 999  # Impassable
        elif self.terrain_type == TerrainType.GRASS:
            self.display_char = ","
            self.blocks_movement = False
            self.blocks_los = False
            self.provides_cover = CoverType.NONE
            self.movement_cost = 1
        elif self.terrain_type == TerrainType.TREE:
            self.display_char = "T"
            # self.blocks_movement = False # Can move into tree space? Maybe not? Let's block for now
            self.blocks_movement = True  # Revisit this - usually can't occupy same space
            self.blocks_los = True  # Blocks LOS
            self.provides_cover = CoverType.HALF
            self.movement_cost = 999  # Cannot move into
        elif self.terrain_type == TerrainType.WATER:
            self.display_char = "~"
            self.blocks_movement = False  # Shallow water
            self.blocks_los = False
            self.provides_cover = CoverType.NONE
            self.movement_cost = 2  # Difficult terrain
        elif self.terrain_type == TerrainType.ROCK:
            self.display_char = "R"
            self.blocks_movement = True  # Assume large rock
            self.blocks_los = True
            self.provides_cover = CoverType.HALF  # Or THREE_QUARTERS? Depends on size
            self.movement_cost = 999
        elif self.terrain_type == TerrainType.RUBBLE:
            self.display_char = ":"
            self.blocks_movement = False
            self.blocks_los = False
            self.provides_cover = CoverType.HALF
            self.movement_cost = 2  # Difficult terrain
        elif self.terrain_type == TerrainType.DOOR:
            self.display_char = "+"  # Closed door
            self.blocks_movement = True  # Initially closed
            self.blocks_los = True  # Initially closed
            self.provides_cover = CoverType.NONE  # Can provide cover if open?
            self.movement_cost = 1  # Cost when open
        elif self.terrain_type == TerrainType.BUILDING_INTERIOR:
            self.display_char = "."  # Same as floor for now
            self.blocks_movement = False
            self.blocks_los = False
            self.provides_cover = CoverType.NONE
            self.movement_cost = 1
        elif self.terrain_type == TerrainType.STREET:
            self.display_char = "="
            self.blocks_movement = False
            self.blocks_los = False
            self.provides_cover = CoverType.NONE
            self.movement_cost = 1
        elif self.terrain_type == TerrainType.CHASM:
            self.display_char = " "
            self.blocks_movement = True  # Can't walk on air
            self.blocks_los = False
            self.provides_cover = CoverType.NONE
            self.movement_cost = 999
            self.hazard = HazardInfo(damage=100, type="fall")  # Lethal fall
        else:
            # Default case if new terrain is added without handling
            self.display_char = "?"
            self.blocks_movement = False
            self.blocks_los = False
            self.provides_cover = CoverType.NONE
            self.movement_cost = 1

        # Update initial display char based purely on terrain
        # Call it once here after setting defaults
        self.update_display_char()  # Call moved to __init__

    def update_display_char(self) -> None:
        """Updates the display character based on the tile's current state."""
        if self.character:
            self.display_char = self.character.name[0]
        elif (
            self.hazard and self.terrain_type != TerrainType.CHASM
        ):  # Chasm handles its own display
            # Simple hazard display - could be more specific later
            self.display_char = (
                "^" if self.terrain_type == TerrainType.FLOOR else self.display_char
            )  # Show hazard on floor
        # Add more conditions for items, cover markers etc. if needed
        else:
            # Revert to terrain default if no character/hazard overrides
            # Re-set display char based on terrain only if nothing else is present
            # Need the original terrain display char logic
            # Let's simplify: Store the base terrain char and restore it.
            # OR: just call _set_properties_from_terrain again?
            # Be careful of recursion if _set_properties calls update_display

            # Simplified approach: Use a map for terrain chars
            terrain_chars = {
                TerrainType.FLOOR: ".",
                TerrainType.WALL: "#",
                TerrainType.GRASS: ",",
                TerrainType.TREE: "T",
                TerrainType.WATER: "~",
                TerrainType.ROCK: "R",
                TerrainType.RUBBLE: ":",
                TerrainType.DOOR: "+",
                TerrainType.BUILDING_INTERIOR: ".",
                TerrainType.STREET: "=",
                TerrainType.CHASM: " ",
            }
            self.display_char = terrain_chars.get(self.terrain_type, "?")

    def __str__(self) -> str:
        """String representation for debugging."""
        char_name = self.character.name if self.character else "None"
        hazard_info = f"Hazard({self.hazard.type})" if self.hazard else "None"
        return (
            f"Tile({self.x},{self.y} Terrain:{self.terrain_type.name} "
            f"Char:{char_name} Hazard:{hazard_info} Cover:{self.provides_cover.name} "
            f"MoveCost:{self.movement_cost} BlocksMove:{self.blocks_movement} BlocksLOS:{self.blocks_los})"
        )
