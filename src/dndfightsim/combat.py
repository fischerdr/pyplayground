"""Handles the core combat simulation logic, including turns and actions."""

import math
import random
from typing import List, Optional, Tuple

from .characters.base import Character
from .characters.classes import Mage, Rogue  # Removed unused Ranger
from .datatypes import ItemDict, StatusEffectDict  # Removed unused Coordinate

# Import necessary components
from .enums import Action, CoverType, StatusEffect
from .environment import BaseEnvironment


def _handle_character_turn(
    character: Character, opponent: Character, environment: BaseEnvironment
) -> Optional[str]:
    """Handles a single character's turn in the fight.

    Processes status effects, applies hazards, chooses and performs an action,
    and handles end-of-turn cleanup.

    Args:
        character: The character whose turn it is.
        opponent: The opposing character.
        environment: The BaseEnvironment object.

    Returns:
        The name of the winner if the turn resulted in victory, otherwise None.
    """
    # Reset movement points at the start of the turn
    character.movement_points = character.DEFAULT_MOVEMENT

    if not character.process_status_effects():
        return None  # Character is stunned or otherwise incapacitated

    # Check if character survived status effects
    if character.hp <= 0:
        print(f"{character.name} succumbed to status effects before acting!")
        return opponent.name

    # Apply hazards based on current tile
    environment.apply_hazards(character)  # Method now exists in BaseEnvironment/BattleGrid
    if character.hp <= 0:
        print(f"{character.name} succumbed to hazards before acting!")
        return opponent.name

    print(f"{character.name}'s turn ({character.class_name.value}):")
    # Pass environment to AI
    action: Action = character.ai.choose_action(opponent, environment)
    winner: Optional[str] = _perform_action(character, opponent, environment, action)

    if winner:
        return winner  # Action resulted in victory

    character.end_turn()
    return None  # Turn completed, no winner yet


def _perform_action(
    character: Character,
    opponent: Character,
    environment: BaseEnvironment,
    action: Action,
) -> Optional[str]:
    """Performs the chosen action for the character.

    Args:
        character: The acting character.
        opponent: The opposing character.
        environment: The BaseEnvironment object.
        action: The Action enum member representing the action to perform.

    Returns:
        The name of the winner if the action resulted in victory, otherwise None.
    """
    winner: Optional[str] = None
    print(f"  Action: {action.value}")

    if action == Action.ATTACK:
        winner = _handle_attack_action(character, opponent, environment)  # Pass environment

    elif action == Action.MOVE:
        _handle_move_action(character, opponent, environment)  # Pass environment

    elif action == Action.DODGE:
        character.dodge()

    elif action == Action.PARRY:
        character.parry()  # TODO: Parry effect needs implementation in attack handling

    elif action == Action.USE_ITEM:
        winner = _handle_item_action(character, opponent)

    # Class-specific actions
    if winner is None and isinstance(character, Mage) and random.random() < 0.3:
        # Spellcasting doesn't currently interact with environment, but pass for consistency
        winner = _handle_mage_spellcasting(character, opponent)

    return winner


def has_line_of_sight(
    start_x: int, start_y: int, end_x: int, end_y: int, environment: BaseEnvironment
) -> bool:
    """Checks if there is a clear line of sight between two points using Bresenham's algorithm.

    Args:
        start_x: Starting x-coordinate.
        start_y: Starting y-coordinate.
        end_x: Ending x-coordinate.
        end_y: Ending y-coordinate.
        environment: The environment grid.

    Returns:
        True if line of sight is clear, False otherwise.
    """
    dx = abs(end_x - start_x)
    dy = -abs(end_y - start_y)
    sx = 1 if start_x < end_x else -1
    sy = 1 if start_y < end_y else -1
    err = dx + dy  # error value e_xy

    x, y = start_x, start_y
    while True:
        # Check the current tile (excluding start and end points)
        if x != start_x or y != start_y:  # Don't check the start tile
            if x == end_x and y == end_y:  # Reached the end
                break  # End tile doesn't block LoS to itself
            tile = environment.get_tile(x, y)
            if tile and tile.blocks_los:
                # print(f"LoS blocked at ({x},{y}) by {tile.terrain_type.name}") # Debug
                return False

        if x == end_x and y == end_y:
            break

        e2 = 2 * err
        if e2 >= dy:  # e_xy+e_x > 0
            err += dy
            x += sx
        if e2 <= dx:  # e_xy+e_y < 0
            err += dx
            y += sy

    return True


def calculate_distance(x1: int, y1: int, x2: int, y2: int) -> float:
    """Calculates Euclidean distance between two points."""
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


# flake8: noqa: C901
def _handle_attack_action(
    character: Character, opponent: Character, environment: BaseEnvironment
) -> Optional[str]:
    """Handles the attack action, calculates hit/miss/damage, and checks for winner.

    Checks weapon range, Line of Sight for ranged attacks, and cover bonuses.
    Applies appropriate stat bonuses based on weapon range.

    Args:
        character: The attacking character.
        opponent: The defending character.
        environment: The BaseEnvironment object.

    Returns:
        The name of the winner if the attack defeated the opponent, otherwise None.
    """
    attack_roll: float
    # Determine weapon range and if it's considered 'ranged' for LoS/Cover/Bonus checks
    weapon_range = character.weapon.get("range", 1.0)  # Default to 1.0 if missing
    is_effectively_ranged = weapon_range > 1.5  # Threshold for LoS/Cover/Dex bonus checks

    # Get character and opponent locations
    char_loc = environment.get_character_location(character)
    opp_loc = environment.get_character_location(opponent)

    if not char_loc or not opp_loc:
        print(
            f"  Error: Cannot find location for {character.name} or {opponent.name}. Attack fails."
        )
        return None

    char_x, char_y = char_loc
    opp_x, opp_y = opp_loc

    distance = calculate_distance(char_x, char_y, opp_x, opp_y)

    # --- Range Check ---
    if distance > weapon_range:
        print(
            f"  {character.name} is out of range! (Distance: {distance:.1f}, Range: {weapon_range:.1f})"
        )
        return None

    # --- Attack Validity and Cover Checks ---
    target_ac_bonus_from_cover = 0
    if is_effectively_ranged:
        # Check Line of Sight for ranged attacks
        if not has_line_of_sight(char_x, char_y, opp_x, opp_y, environment):
            print(f"  {character.name}'s ranged attack is blocked! (No LoS)")
            return None

        # Check Target Cover for ranged attacks
        target_tile = environment.get_tile(opp_x, opp_y)
        if target_tile and target_tile.provides_cover != CoverType.NONE:
            if target_tile.provides_cover == CoverType.HALF:
                target_ac_bonus_from_cover = 2
                print(f"  {opponent.name} has half cover (+2 AC)!")
            elif target_tile.provides_cover == CoverType.THREE_QUARTERS:
                target_ac_bonus_from_cover = 5
                print(f"  {opponent.name} has three-quarters cover (+5 AC)!")
            # TODO: Handle FULL cover? Does it just block LoS?

        # Perform attack roll with Dexterity bonus for ranged
        print(
            f"  {character.name} makes a ranged attack! Roll vs AC: {opponent.ac + target_ac_bonus_from_cover}"
        )
        attack_roll = character.perform_attack_roll(ranged=True)
    else:  # Melee Attack
        # Perform attack roll with Strength bonus for melee
        print(f"  {character.name} attacks! Roll vs AC: {opponent.ac}")
        attack_roll = character.perform_attack_roll(ranged=False)

    # --- Attack Roll and Damage Calculation ---
    # Handle critical miss
    if attack_roll == float("-inf"):
        print("  Critical Miss!")
        return None

    is_critical_hit = attack_roll == float("inf")

    # Check for hit (crit success or roll >= effective AC)
    effective_ac = opponent.ac + target_ac_bonus_from_cover
    if is_critical_hit or attack_roll >= effective_ac:
        # --- Calculate base damage and bonus ---
        # Base damage from weapon
        base_damage = character.deal_damage()

        # Stat bonus based on whether it's effectively ranged
        if is_effectively_ranged:
            damage_bonus = (character.dexterity - 10) // 2
        else:
            damage_bonus = (character.strength - 10) // 2

        damage = max(0, base_damage + damage_bonus)

        # Apply critical hit bonus damage (using base weapon damage)
        if is_critical_hit:
            # Recalculate base damage for crit bonus (as deal_damage doesn't include it)
            crit_bonus = random.randint(
                character.weapon["damage"][0], character.weapon["damage"][1]
            )
            print(f"  Critical Hit! Extra Damage: {crit_bonus}")
            damage += crit_bonus

        # Apply Rogue sneak attack bonus
        if isinstance(character, Rogue):
            # TODO: Implement proper sneak attack conditions (advantage, ally adjacent)
            # Sneak attack only applies if using a finesse or ranged weapon (simplification: check range)
            if (
                is_effectively_ranged or character.weapon.get("name") == "Dagger"
            ):  # Example finesse weapon check
                if random.random() < 0.2:
                    sneak_bonus = character._calculate_sneak_attack_damage()
                    damage += sneak_bonus

        print(f"  {character.name} hits {opponent.name} for {damage} damage.")
        if opponent.take_damage(damage):
            print(f"  {opponent.name} has been defeated!")
            return character.name

        # Apply status effect on hit (random chance)
        if random.random() < 0.1:
            effect_type_enum: StatusEffect = random.choice(
                [StatusEffect.POISONED, StatusEffect.STUNNED]
            )
            duration: int = 3 if effect_type_enum == StatusEffect.POISONED else 1
            effect: StatusEffectDict = {"name": effect_type_enum.value, "duration": duration}
            print(f"  {opponent.name} is now {effect_type_enum.value}!")
            opponent.apply_status_effect(effect)
    else:
        print(f"  {character.name} misses {opponent.name}.")

    return None


def _handle_move_action(
    character: Character, opponent: Character, environment: BaseEnvironment
) -> None:
    """Handles the move action, checking movement cost.

    Args:
        character: The moving character.
        opponent: The opposing character.
        environment: The BaseEnvironment object.
    """
    # Get current location first
    start_pos = environment.get_character_location(character)
    if not start_pos:
        print(f"  Error: Cannot find {character.name}'s starting position.")
        return

    start_x, start_y = start_pos

    # AI chooses a single step direction
    dx: int
    dy: int
    dx, dy = character.ai.choose_move_direction(environment, opponent)
    if dx == 0 and dy == 0:
        print(f"  {character.name} decides to stay put or cannot move.")
        return

    # Calculate target position
    target_x = start_x + dx
    target_y = start_y + dy

    # Check if target tile is valid and get its cost
    target_tile = environment.get_tile(target_x, target_y)
    if not target_tile:
        print(f"  {character.name} tries to move off the grid. Invalid move.")
        return

    move_cost: int = target_tile.movement_cost

    # Check if character has enough movement points
    if character.movement_points < move_cost:
        print(
            f"  {character.name} does not have enough movement points (needs {move_cost}, has {character.movement_points})."
        )
        return

    # Attempt the move
    if environment.move_character(character, dx, dy):
        character.movement_points -= move_cost  # Deduct cost
        new_pos = (target_x, target_y)  # We already calculated the target pos
        print(
            f"  {character.name} moves ({dx},{dy}) to {new_pos} (Cost: {move_cost}, Remaining MP: {character.movement_points})."
        )
        print(f"Grid after {character.name}'s move:")
        print(environment)
    else:
        # Environment.move_character already handles printing failure reasons
        # (e.g., blocked, occupied)
        # print(f"  {character.name} attempted an invalid move to ({target_x}, {target_y}). Staying put.")
        pass  # Failure reason printed by environment.move_character


def _handle_item_action(character: Character, opponent: Character) -> Optional[str]:
    """Handles the use item action and checks for a winner.

    Args:
        character: The character using the item.
        opponent: The opposing character.

    Returns:
        The name of the winner if the item defeated the opponent, otherwise None.
    """
    item: Optional[ItemDict] = character.use_item()
    if item:
        item_type_str = item.get("type", "unknown")
        item_name = item.get("name", "Unknown Item")

        if item_type_str == "damage":
            damage_range: Tuple[int, int] = item.get("damage", (0, 0))
            damage: int = random.randint(damage_range[0], damage_range[1])
            print(f"  {character.name} uses {item_name} on {opponent.name} for {damage} damage.")
            if opponent.take_damage(damage):
                print(f"  {opponent.name} has been defeated!")
                return character.name
    return None


def _handle_mage_spellcasting(mage: Mage, opponent: Character) -> Optional[str]:
    """Handles the Mage's spellcasting action (offensive or defensive) and checks for winner.

    Args:
        mage: The Mage character casting the spell.
        opponent: The opposing character.

    Returns:
        The name of the winner if an offensive spell defeated the opponent, otherwise None.
    """
    if mage.spell_slots > 0:
        spell_type_str: str = random.choice(["offensive", "defensive"])
        print(f"  {mage.name} decides to cast a {spell_type_str} spell.")

        if spell_type_str == "offensive":
            spell_name: Optional[str]
            damage: int
            spell_name, damage = mage.cast_offensive_spell()
            if spell_name:
                print(f"  {mage.name} casts {spell_name} on {opponent.name} for {damage} damage!")
                if opponent.take_damage(damage):
                    print(f"  {opponent.name} has been defeated!")
                    return mage.name
            else:
                print(f"  {mage.name} fizzles the offensive spell (no slots?).")
        else:
            heal_or_ac: int = mage.cast_defensive_spell()
            if heal_or_ac == 0 and mage.spell_slots <= 0:
                print(f"  {mage.name} fizzles the defensive spell (no slots?).")
    else:
        print(f"  {mage.name} is out of spell slots!")

    return None


def _determine_winner_post_loop(
    character1: Character, character2: Character, turn_count: int, max_turns: int
) -> str:
    """Determines the winner based on HP after the main fight loop.

    Handles max turns condition.

    Args:
        character1: The first character.
        character2: The second character.
        turn_count: The number of turns elapsed.
        max_turns: The maximum allowed turns.

    Returns:
        The name of the winning character or a Draw reason string.
    """
    print(f"\n--- Battle Concluded ({turn_count} turns) --- Final State:")
    print(f"  {character1.name}: HP {character1.hp}")
    print(f"  {character2.name}: HP {character2.hp}")

    c1_alive = character1.hp > 0
    c2_alive = character2.hp > 0

    if c1_alive and not c2_alive:
        return character1.name
    elif c2_alive and not c1_alive:
        return character2.name
    elif not c1_alive and not c2_alive:
        return "Draw (Mutual Destruction)"
    elif turn_count >= max_turns:
        print("  Max turns reached!")
        hp_perc1: float = (
            character1.hp / (character1.constitution * 2) if character1.constitution > 0 else 0
        )
        hp_perc2: float = (
            character2.hp / (character2.constitution * 2) if character2.constitution > 0 else 0
        )
        if hp_perc1 > hp_perc2:
            return character1.name
        elif hp_perc2 > hp_perc1:
            return character2.name
        else:
            return "Draw (Max Turns Reached - Equal HP %)"
    else:
        print("Warning: Unexpected state at end of fight loop.")
        return "Draw (Unknown Reason)"


def fight(
    character1: Character, character2: Character, environment: BaseEnvironment
) -> str:  # Renamed parameter
    """Simulates a fight between two characters on a battle grid.

    Handles turn order, AI actions, attacks, damage, status effects, hazards,
    and determines the winner.

    Args:
        character1: The first Character object.
        character2: The second Character object.
        environment: The BaseEnvironment object for the fight.

    Returns:
        The name of the winning character, or "Draw" if somehow neither wins.
    """
    print(f"\n--- Battle Begins: {character1.name} vs {character2.name} ---")
    # Get character locations from the environment
    char1_loc = environment.get_character_location(character1)
    char2_loc = environment.get_character_location(character2)
    print(f"{character1.name} ({character1.personality.value}) starts at {char1_loc}")
    print(f"{character2.name} ({character2.personality.value}) starts at {char2_loc}")
    print("Initial Grid:")
    print(environment)  # Print the environment directly
    print("-" * 20)

    # Ensure characters have HP before starting
    if character1.hp <= 0:
        print(f"{character1.name} starts defeated.")
        return character2.name
    if character2.hp <= 0:
        print(f"{character2.name} starts defeated.")
        return character1.name

    characters: List[Character] = [character1, character2]
    random.shuffle(characters)
    print(f"{characters[0].name} wins initiative and goes first.")

    turn_count: int = 0
    max_turns: int = 100
    winner: Optional[str] = None

    while character1.hp > 0 and character2.hp > 0 and turn_count < max_turns:
        turn_count += 1
        print(f"\n=== Turn {turn_count} ===")
        for i, current_char in enumerate(characters):
            opponent: Character = characters[1 - i]

            if opponent.hp <= 0:
                winner = current_char.name
                break

            if current_char.hp <= 0:
                winner = opponent.name
                break

            turn_winner: Optional[str] = _handle_character_turn(current_char, opponent, environment)
            if turn_winner:
                winner = turn_winner
                break

            print(f"  Status -> {current_char.name}: HP {current_char.hp}, AC {current_char.ac}")
            print(f"            {opponent.name}: HP {opponent.hp}, AC {opponent.ac}")

        if winner:
            break

    if not winner:
        winner = _determine_winner_post_loop(character1, character2, turn_count, max_turns)

    print(f"\n--- Battle Over --- Final Result: {winner} --- ({turn_count} turns)")
    return winner
