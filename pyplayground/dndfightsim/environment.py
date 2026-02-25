"""Defines the combat environment, including the grid, tiles, and characters."""

import abc
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from rich.text import Text  # Import rich.text

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
        return [[Tile(terrain_type=TerrainType.FLOOR, x=x, y=y) for x in range(self.width)] for y in range(self.height)]

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
            raise ValueError(f"Cannot place character on blocked terrain: {tile.terrain_type.name} at ({x},{y})")
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
        return "\n".join(["".join([tile.display_char for tile in row]) for row in self.grid])  # Use display_char attribute


# --- BattleGrid Implementation (inherits from BaseEnvironment) ---


class BattleGrid(BaseEnvironment):
    """Represents the battle grid with specific features like cover and hazards."""

    def __init__(self, width: int, height: int):
        """Initializes the BattleGrid, setting up the grid with Tile objects."""
        super().__init__(width, height)
        self._character_style_map: Dict[str, str] = {}  # Cache styles per character name
        self.targeting_line: Optional[Tuple[Coordinate, Coordinate]] = None

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
            if not tile.blocks_movement:  # Don't add hazard display to walls etc.
                tile.hazard = HazardInfo(damage=damage, hazard_type=hazard_type)
                # tile.display_char = 'H' # Let update_display_char handle it
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
        """Checks if a character is benefiting from cover.

        Simplified: Checks if the character's tile provides cover.
        A more complex check would involve line of sight from attackers.

        Args:
            character: The character to check.

        Returns:
            True if the character's tile provides cover, False otherwise.
        """
        location = self.get_character_location(character)
        if not location:
            return False
        x, y = location
        tile = self.get_tile(x, y)
        return tile.provides_cover != CoverType.NONE if tile else False

    def apply_hazards(self, character: "Character") -> List[str]:
        """Applies hazard damage if the character is on a hazard tile.

        Args:
            character: The Character object to check.

        Returns:
            A list of log messages generated by the hazard application.
        """
        logs = []
        location = self.get_character_location(character)
        if not location:
            return logs  # No location, no hazard
        x, y = location

        tile = self.get_tile(x, y)
        if tile and tile.hazard:
            logs.append(f"Hazard ({tile.hazard.hazard_type}) at ({x},{y}) affects {character.name}!")
            # Import Character locally if needed, or ensure it's available
            # from .characters.base import Character # Avoid top-level circular import
            if character.take_damage(tile.hazard.damage):
                logs.append(f"  {character.name} was defeated by the hazard!")
            else:
                logs.append(f"  {character.name} takes {tile.hazard.damage} damage.")
        return logs

    def _calculate_line_points(self, x0: int, y0: int, x1: int, y1: int) -> Set[Coordinate]:
        """Calculates points on a line using Bresenham's algorithm. Helper for LoS/Targeting."""
        points = set()
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy

        x, y = x0, y0
        while True:
            points.add((x, y))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy
        return points

    def render_rich(self) -> Text:
        """Generates a rich Text object representing the grid state."""
        grid_text = Text()
        # Define styles for different elements
        styles = {
            TerrainType.FLOOR: "grey50 on grey15",
            TerrainType.WALL: "bold white on black",
            TerrainType.GRASS: "green on dark_green",
            TerrainType.TREE: "bold green on dark_green",
            TerrainType.WATER: "blue on dark_blue",
            TerrainType.ROCK: "bold grey70 on grey30",
            TerrainType.RUBBLE: "yellow on grey30",
            TerrainType.DOOR: "bold yellow on saddle_brown",
            TerrainType.CAVE_WALL: "bold grey82 on grey30",
            TerrainType.CHASM: "bold white on black",
            TerrainType.BUILDING_INTERIOR: "wheat4 on grey15",
            TerrainType.STREET: "grey70 on grey30",
            "character_default": "bold white",  # Default if name not mapped
            "hazard": "bold red",
            "cover_half": "underline",  # Style for half cover tile itself
            "cover_three_quarters": "bold underline",  # Style for 3/4 cover
            "targeting": "on bright_yellow",  # Style for targeting line
        }

        # Simple color cycle for characters
        char_colors = [
            "bright_red",
            "bright_blue",
            "bright_green",
            "bright_magenta",
            "bright_cyan",
            "bright_yellow",
        ]
        char_color_idx = 0

        # Calculate targeting line points if active
        targeting_points: Set[Coordinate] = set()
        if self.targeting_line:
            start_coord, end_coord = self.targeting_line
            targeting_points = self._calculate_line_points(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
            # Exclude the start and end points themselves from the line highlight? Optional.
            # targeting_points.discard(start_coord)
            # targeting_points.discard(end_coord)

        for y in range(self.height):
            for x in range(self.width):
                tile = self.grid[y][x]
                display_char = tile.display_char
                style = styles.get(tile.terrain_type, "default")
                is_target_path = (x, y) in targeting_points

                # Apply cover style to the tile background/base style
                if tile.provides_cover == CoverType.HALF:
                    style = f"{style} {styles['cover_half']}"
                elif tile.provides_cover == CoverType.THREE_QUARTERS:
                    style = f"{style} {styles['cover_three_quarters']}"

                # Override character display and style
                if tile.character:
                    display_char = tile.character.get_display_char()  # Get first letter
                    # Assign a color if not already seen
                    if tile.character.name not in self._character_style_map:
                        self._character_style_map[tile.character.name] = char_colors[char_color_idx % len(char_colors)]
                        char_color_idx += 1
                    # char_style = f"{styles['character_default']} on {style.split(' on ')[-1]}"  # Base char style on tile bg - UNUSED
                    char_color = self._character_style_map[tile.character.name]
                    style = f"bold {char_color} on {style.split(' on ')[-1]}"  # Final style for char tile
                elif tile.hazard:
                    display_char = tile.get_hazard_display_char()
                    # Apply hazard style on top of terrain style
                    hazard_style = styles["hazard"]
                    style = f"{hazard_style} on {style.split(' on ')[-1]}"

                # Apply targeting line style - Overrides background color
                if is_target_path and not tile.character:  # Don't override character tile BG
                    style_parts = style.split(" on ")
                    foreground = style_parts[0]
                    # style = f"{foreground} {styles['targeting']}" # Simple override
                    style = f"{foreground} {styles['targeting']}"
                grid_text.append(display_char, style=style)
            grid_text.append("\n")
        return grid_text

    # __str__ is inherited from BaseEnvironment

    # Remove the duplicated __str__ method from here
    # It should be inherited from BaseEnvironment
    # ... existing code ...
