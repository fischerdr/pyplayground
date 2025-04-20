"""Defines the combat environment, including the grid, tiles, and characters."""

import abc
from typing import TYPE_CHECKING, Dict, List, Optional

from .datatypes import Coordinate, HazardInfo  # Removed HazardTuple
from .enums import CoverType, TerrainType

# Import Tile and related types
from .tiles import Tile

if TYPE_CHECKING:
    from .characters.base import Character

    # from .datatypes import Coordinate, HazardInfo # Already imported above


class BaseEnvironment(abc.ABC):
    """Abstract base class for combat environments."""

    def __init__(self, width: int, height: int):
        """Initializes the environment grid."""
        self.width: int = width
        self.height: int = height
        self.grid: List[List[Tile]] = self._create_empty_grid()
        # Keep track of character locations for quick lookup
        self.character_locations: Dict["Character", Coordinate] = {}

    def _create_empty_grid(self) -> List[List[Tile]]:
        """Creates a grid filled with default floor tiles."""
        return [
            [Tile(terrain_type=TerrainType.FLOOR, x=x, y=y) for x in range(self.width)]
            for y in range(self.height)
        ]

    def is_valid_coordinate(self, x: int, y: int) -> bool:
        """Checks if the given coordinates are within the grid bounds."""
        return 0 <= x < self.width and 0 <= y < self.height

    def get_tile(self, x: int, y: int) -> Optional[Tile]:
        """Returns the Tile object at the given coordinates, or None if invalid."""
        if self.is_valid_coordinate(x, y):
            return self.grid[y][x]
        return None

    def place_character(self, character: "Character", x: int, y: int) -> None:
        """Places a character on the grid at the specified coordinates.

        Args:
            character: The Character object to place.
            x: The x-coordinate.
            y: The y-coordinate.

        Raises:
            ValueError: If the position (x, y) is invalid or occupied.
        """
        tile = self.get_tile(x, y)
        if tile is None:
            raise ValueError(f"Invalid coordinates: ({x},{y})")
        if tile.blocks_movement:
            raise ValueError(
                f"Cannot place character on blocked terrain: {tile.terrain_type.name} at ({x},{y})"
            )
        if tile.character is not None:
            raise ValueError(f"Tile ({x},{y}) is already occupied by {tile.character.name}")

        # Remove character from old tile if they were already placed
        if character in self.character_locations:
            old_x, old_y = self.character_locations[character]
            old_tile = self.get_tile(old_x, old_y)
            if old_tile:
                old_tile.character = None
                old_tile.update_display_char()

        # Place character on new tile
        tile.character = character
        tile.update_display_char()
        self.character_locations[character] = (x, y)

    def move_character(self, character: "Character", dx: int, dy: int) -> bool:
        """Moves a character on the grid by dx and dy.

        Checks for valid coordinates and blocked movement.

        Args:
            character: The Character object to move.
            dx: The change in the x-coordinate.
            dy: The change in the y-coordinate.

        Returns:
            True if the move was successful, False otherwise.
        """
        if character not in self.character_locations:
            print(f"Error: Cannot move {character.name}, not found on grid.")
            return False

        x, y = self.character_locations[character]
        new_x, new_y = x + dx, y + dy

        new_tile = self.get_tile(new_x, new_y)

        if new_tile is None:
            # print(f"Debug: Move failed for {character.name} - invalid coords ({new_x},{new_y})")
            return False  # Off grid

        if new_tile.blocks_movement:
            # print(f"Debug: Move failed for {character.name} - blocked movement at ({new_x},{new_y})")
            return False  # Blocked by terrain

        if new_tile.character is not None:
            # print(f"Debug: Move failed for {character.name} - tile ({new_x},{new_y}) occupied by {new_tile.character.name}")
            return False  # Blocked by another character

        # Get old tile and update
        old_tile = self.get_tile(x, y)
        if old_tile:
            old_tile.character = None
            old_tile.update_display_char()

        # Update new tile
        new_tile.character = character
        new_tile.update_display_char()

        # Update character location map
        self.character_locations[character] = (new_x, new_y)
        return True

    def get_characters(self) -> List["Character"]:
        """Returns a list of all characters currently on the grid."""
        return list(self.character_locations.keys())

    def get_character_location(self, character: "Character") -> Optional[Coordinate]:
        """Returns the coordinates of a specific character."""
        return self.character_locations.get(character)

    @abc.abstractmethod
    def generate(self) -> None:
        """Abstract method to generate the specific environment layout."""
        pass

    def __str__(self) -> str:
        """Returns a string representation of the grid, showing tile contents."""
        # Iterate through each tile and get its display character
        return "\n".join(
            [
                "".join([tile.display_char for tile in row])  # Use display_char attribute
                for row in self.grid
            ]
        )


# --- BattleGrid Implementation (inherits from BaseEnvironment) ---


class BattleGrid(BaseEnvironment):
    """Represents the battle grid with specific features like cover and hazards."""

    def __init__(self, width: int, height: int):
        """Initializes the BattleGrid, setting up the grid with Tile objects."""
        super().__init__(width, height)

    def generate(self) -> None:
        """Generates the layout for this specific BattleGrid instance.

        Currently just ensures the grid is created (done in super().__init__).
        Can be overridden or extended to add specific features like the example fight setup.
        """
        print(f"Generated a basic {self.width}x{self.height} floor grid.")

    # These methods now modify Tile properties directly
    def add_cover(self, x: int, y: int, cover_type: CoverType = CoverType.HALF) -> None:
        """Adds cover to a specific tile.

        Args:
            x: The x-coordinate of the cover.
            y: The y-coordinate of the cover.
            cover_type: The type of cover to add (default: HALF).
        """
        tile = self.get_tile(x, y)
        if tile:
            if not tile.blocks_movement:  # Don't add cover display to walls etc.
                tile.provides_cover = cover_type
                tile.display_char = "c" if cover_type == CoverType.HALF else "C"
                tile.update_display_char()
            else:
                print(f"Warning: Cannot add cover to blocked tile ({x},{y})")
        else:
            print(f"Warning: Cannot add cover to invalid tile ({x},{y})")

    def add_hazard(self, x: int, y: int, damage: int, hazard_type: str = "generic") -> None:
        """Adds a hazard to a specific tile.

        Args:
            x: The x-coordinate of the hazard.
            y: The y-coordinate of the hazard.
            damage: The amount of damage the hazard deals.
            hazard_type: A string describing the type of hazard (e.g., 'fire').
        """
        tile = self.get_tile(x, y)
        if tile:
            if not tile.blocks_movement:
                tile.hazard = HazardInfo(damage=damage, type=hazard_type)
                tile.display_char = "^"
                tile.update_display_char()
            else:
                print(f"Warning: Cannot add hazard to blocked tile ({x},{y})")
        else:
            print(f"Warning: Cannot add hazard to invalid tile ({x},{y})")

    # NOTE: is_in_cover and apply_hazards are intentionally kept here for now
    # as their logic might be specific to BattleGrid or needs further refinement
    # based on BaseEnvironment capabilities (like LOS for cover).
    # However, the base BaseEnvironment already provides character location lookups.

    def is_in_cover(self, character: "Character") -> bool:
        """Checks if a character benefits from cover provided by adjacent tiles.

        NOTE: This is a simplified check. Real cover depends on the attacker's position.
        This checks if *any* adjacent tile provides cover.

        Args:
            character: The Character object to check.

        Returns:
            True if any adjacent tile provides cover, False otherwise.
        """
        location = self.get_character_location(character)
        if not location:
            return False
        x, y = location

        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                adj_tile = self.get_tile(x + dx, y + dy)
                if adj_tile and adj_tile.provides_cover != CoverType.NONE:
                    return True
        return False

    def apply_hazards(self, character: "Character") -> None:
        """Applies hazard damage if the character is on a hazard tile.

        Args:
            character: The Character object to check.
        """
        location = self.get_character_location(character)
        if not location:
            return
        x, y = location

        tile = self.get_tile(x, y)
        if tile and tile.hazard:
            print(f"Hazard ({tile.hazard.type}) at ({x},{y}) affects {character.name}!")
            # Import Character locally if needed, or ensure it's available
            # from .characters.base import Character # Avoid top-level circular import
            if character.take_damage(tile.hazard.damage):
                print(f"  {character.name} was defeated by the hazard!")
            else:
                print(f"  {character.name} takes {tile.hazard.damage} damage.")

    # __str__ is inherited from BaseEnvironment

    # Remove the duplicated __str__ method from here
    # It should be inherited from BaseEnvironment
    # ... existing code ...
