"""Contains functions for procedurally generating different environment types."""

import random
from typing import TYPE_CHECKING, List, Set, Tuple

if TYPE_CHECKING:
    from .environment import BattleGrid

    # from .tiles import Tile # Unused

# Import BattleGrid directly, avoid redefinition F811
from .enums import TerrainType
from .environment import BattleGrid as GridEnv  # Alias to avoid potential namespace conflicts


def _grow_cluster(
    environment: "GridEnv",
    start_x: int,
    start_y: int,
    terrain_type: TerrainType,
    max_size: int,
    spread_prob: float,
):
    """Helper to grow a cluster of a specific terrain type."""
    cluster_tiles: Set[Tuple[int, int]] = set()
    frontier: List[Tuple[int, int]] = [(start_x, start_y)]
    visited: Set[Tuple[int, int]] = set()

    while frontier and len(cluster_tiles) < max_size:
        current_x, current_y = frontier.pop(random.randrange(len(frontier)))  # Random pop for irregularity

        if not environment.is_valid_coordinate(current_x, current_y) or (current_x, current_y) in visited:
            continue

        visited.add((current_x, current_y))
        tile = environment.get_tile(current_x, current_y)

        # Only place on grass and if random chance allows
        if tile and tile.terrain_type == TerrainType.GRASS and random.random() < spread_prob:
            tile.terrain_type = terrain_type
            tile._set_properties_from_terrain()
            # Don't update display char yet, do it at the end
            cluster_tiles.add((current_x, current_y))

            # Add neighbors to frontier
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    next_x, next_y = current_x + dx, current_y + dy
                    if (next_x, next_y) not in visited:
                        frontier.append((next_x, next_y))


# flake8: noqa: C901
def generate_field_environment(width: int, height: int) -> "GridEnv":
    """Generates a field environment with clustered trees/rocks, and scattered water/rubble."""
    environment = GridEnv(width, height)

    # 1. Initialize with Grass
    for y in range(height):
        for x in range(width):
            tile = environment.grid[y][x]  # Grid is already filled with tiles
            if tile.terrain_type != TerrainType.GRASS:
                tile.terrain_type = TerrainType.GRASS
                tile._set_properties_from_terrain()
                # Display char update happens at the end

    # 2. Generate Clusters
    num_tree_clusters = random.randint(1, max(1, (width * height) // 100))  # Example scaling
    num_rock_clusters = random.randint(0, max(1, (width * height) // 150))
    max_cluster_size = 10
    cluster_spread_prob = 0.6  # Chance to place feature when expanding cluster

    for _ in range(num_tree_clusters):
        start_x = random.randint(0, width - 1)
        start_y = random.randint(0, height - 1)
        _grow_cluster(environment, start_x, start_y, TerrainType.TREE, max_cluster_size, cluster_spread_prob)

    for _ in range(num_rock_clusters):
        start_x = random.randint(0, width - 1)
        start_y = random.randint(0, height - 1)
        _grow_cluster(
            environment,
            start_x,
            start_y,
            TerrainType.ROCK,
            max_cluster_size // 2,
            cluster_spread_prob * 0.8,
        )

    # 3. Randomly sprinkle other features (Water, Rubble)
    water_prob = 0.02
    rubble_prob = 0.04
    for y in range(height):
        for x in range(width):
            tile = environment.grid[y][x]
            # Only place if still grass
            if tile.terrain_type == TerrainType.GRASS:
                rand_val = random.random()
                if rand_val < water_prob:
                    tile.terrain_type = TerrainType.WATER
                    tile._set_properties_from_terrain()
                elif rand_val < water_prob + rubble_prob:
                    tile.terrain_type = TerrainType.RUBBLE
                    tile._set_properties_from_terrain()

    # 4. Update all display characters at the end
    for y in range(height):
        for x in range(width):
            environment.grid[y][x].update_display_char()

    print(f"Generated a {width}x{height} field environment with clusters.")
    return environment


# TODO: Add path generation
# TODO: Add more hazard types
# TODO: Add generators for CaveEnvironment, CityEnvironment, etc.
# Cave generator could use Cellular Automata or Random Walk.
# City generator could use grid-based building placement.
