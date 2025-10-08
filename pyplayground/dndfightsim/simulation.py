"""Contains the main simulation loops for leveling and example fights."""

import queue
import random
import threading
from typing import List, Optional

# --- Rich Imports --- #
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

console = Console()
# --- End Rich Imports --- #

from .characters.base import Character
from .characters.classes import Mage, Ranger, Rogue, Warrior
from .combat import fight

# Import necessary components from the package
from .enums import CharacterClass

# Import BaseEnvironment and BattleGrid (or just BattleGrid if Base is only for inheritance)
from .environment import BaseEnvironment, BattleGrid
from .generators import generate_field_environment


# --- Timed Input Helper --- #
def timed_input(prompt: str, timeout: float) -> Optional[str]:
    """Asks for input but times out after a specified period."""
    q = queue.Queue()

    def ask_input():
        # Prompt.ask handles the actual user interaction
        response = Prompt.ask(prompt, default="", show_default=False)
        q.put(response)

    thread = threading.Thread(target=ask_input, daemon=True)
    thread.start()

    try:
        # Wait for the specified timeout
        result = q.get(timeout=timeout)
        return result
    except queue.Empty:
        # Timeout occurred
        console.print(
            "\n[dim](Timeout reached, continuing...)[/dim]"
        )  # Add a newline for clarity after timeout
        return None


# --- End Timed Input Helper --- #


def create_random_character(name: str, character_class_enum: CharacterClass) -> Character:
    """Creates a character of a specified class.

    Args:
        name: The name for the character.
        character_class_enum: The desired class as a CharacterClass Enum member.

    Returns:
        An instance of the specified Character subclass.
    """
    character: Character
    if character_class_enum == CharacterClass.WARRIOR:
        character = Warrior(name)
    elif character_class_enum == CharacterClass.MAGE:
        character = Mage(name)
    elif character_class_enum == CharacterClass.RANGER:
        character = Ranger(name)
    elif character_class_enum == CharacterClass.ROGUE:
        character = Rogue(name)
    else:
        print(
            f"Warning: Unknown character class '{character_class_enum}', creating base Character."
        )
        character = Character(name)

    return character


# flake8: noqa: C901
def run_leveling_simulation(num_fights: int = 5):
    """Runs a series of fights to level up characters."""
    print("\n--- Initializing Characters ---")
    character1 = create_random_character("Gandalf", CharacterClass.MAGE)
    character2 = create_random_character("Aragorn", CharacterClass.WARRIOR)
    character3 = create_random_character("Legolas", CharacterClass.RANGER)
    character4 = create_random_character("Bilbo", CharacterClass.ROGUE)
    all_characters = [character1, character2, character3, character4]
    for char in all_characters:
        print(char)

    print("\n--- Leveling Fights Start ---")
    for i in range(num_fights):
        print(f"\nBattle {i + 1}: Leveling Fight")
        if len(all_characters) < 2:
            print("Not enough characters to fight.")
            break
        fighters: List[Character] = random.sample(all_characters, 2)
        fighter_a, fighter_b = fighters[0], fighters[1]

        print(f"Fighting: {fighter_a.name} vs {fighter_b.name}")

        # Create a new simple grid for this leveling fight
        # Use BattleGrid which inherits from BaseEnvironment
        leveling_environment: BaseEnvironment = BattleGrid(5, 5)

        # Place fighters using the environment method
        try:
            leveling_environment.place_character(fighter_a, 0, 0)
            leveling_environment.place_character(fighter_b, 4, 4)
        except ValueError as e:
            print(f"Error placing characters on grid: {e}")
            continue

        hp_before_fight = {fighter_a: fighter_a.hp, fighter_b: fighter_b.hp}

        # Pass the environment object to fight
        winner_name = fight(fighter_a, fighter_b, leveling_environment)

        for fighter in fighters:
            if fighter in hp_before_fight:
                fighter.hp = hp_before_fight[fighter]
            fighter.status_effects = []
            if isinstance(fighter, Mage):
                if fighter.active_defense_spell:
                    fighter.ac -= fighter.active_defense_spell.get("ac_bonus", 0)
                fighter.active_defense_spell = None
                fighter.defense_spell_duration = 0
                fighter.spell_slots = 3
            fighter.end_turn()

        # --- Add Pause Here --- #
        if i < num_fights - 1:  # Don't pause after the last fight
            timed_input(
                f"[dim]Press Enter to continue to Battle {i + 2} or wait 5s...[/dim]", timeout=5.0
            )
        else:
            print("Leveling simulation finished.")
        # --- End Pause --- #

    print("\n--- Leveling Fights End ---")

    print("\n--- Final Character Stats After Leveling ---")
    for character in all_characters:
        print(str(character))


# flake8: noqa: C901
def run_example_grid_fight():
    """Runs a single fight on a procedurally generated field grid."""
    print("\n--- Example Grid Fight ---")

    # Use the procedural generator
    grid_width = 10
    grid_height = 8
    environment_main: BaseEnvironment = generate_field_environment(grid_width, grid_height)

    char_a = create_random_character("Hero", CharacterClass.WARRIOR)
    char_b = create_random_character("Goblin", CharacterClass.ROGUE)

    print("\n--- Initial Characters for Grid Fight ---")
    print(char_a)
    print(char_b)

    # --- Place characters on valid starting tiles --- Find first available spots
    placed_a = False
    for y in range(grid_height):
        for x in range(grid_width):
            tile = environment_main.get_tile(x, y)
            if tile and not tile.blocks_movement and tile.character is None:
                try:
                    environment_main.place_character(char_a, x, y)
                    print(f"Placed {char_a.name} at ({x}, {y})")
                    placed_a = True
                    break
                except ValueError as e:
                    print(
                        f"Error placing {char_a.name} at ({x},{y}): {e}"
                    )  # Should not happen with check
        if placed_a:
            break
    if not placed_a:
        print(f"Could not find a valid starting position for {char_a.name}!")
        return  # Cannot run fight

    placed_b = False
    # Start search from the opposite corner for variety
    for y in range(grid_height - 1, -1, -1):
        for x in range(grid_width - 1, -1, -1):
            tile = environment_main.get_tile(x, y)
            if tile and not tile.blocks_movement and tile.character is None:
                try:
                    environment_main.place_character(char_b, x, y)
                    print(f"Placed {char_b.name} at ({x}, {y})")
                    placed_b = True
                    break
                except ValueError as e:
                    print(
                        f"Error placing {char_b.name} at ({x},{y}): {e}"
                    )  # Should not happen with check
        if placed_b:
            break
    if not placed_b:
        print(
            f"Could not find a valid starting position for {char_b.name}! Placing {char_a.name} failed? Aborting."
        )
        # Optionally remove char_a from grid if placement failed
        if char_a in environment_main.character_locations:
            loc_a = environment_main.get_character_location(char_a)
            if loc_a:
                tile_a = environment_main.get_tile(loc_a[0], loc_a[1])
                if tile_a:
                    tile_a.character = None
            del environment_main.character_locations[char_a]
        return  # Cannot run fight

    # Pass environment object to fight
    winner_name = fight(char_a, char_b, environment_main)

    # --- Add Pause Here ---
    timed_input(f"[dim]Press Enter to exit or wait 5s...[/dim]", timeout=5.0)


# --- Main Execution Guard --- #
# This part will typically be in the main entry point script (e.g., dndfightsim.py)
# For now, keep it here for testing.
# if __name__ == "__main__":
#     run_leveling_simulation()
#     run_example_grid_fight()
