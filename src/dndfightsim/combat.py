"""Handles the core combat simulation logic, including turns and actions."""

import math
import random
from typing import List, Optional, Tuple

from rich.layout import Layout

# --- Rich Display Imports ---
from rich.live import Live

from .characters.base import Character
from .characters.classes import Mage, Rogue  # Removed unused Ranger
from .datatypes import ItemDict, StatusEffectDict  # Removed unused Coordinate
from .display import console, create_layout, update_layout  # Import console for final print

# Import necessary components
from .enums import Action, CoverType, StatusEffect
from .environment import BaseEnvironment, BattleGrid  # Ensure BattleGrid is imported

# --- End Rich Display Imports ---


def _handle_character_turn(
    character: Character, opponent: Character, environment: BaseEnvironment, log_messages: List[str]
) -> bool:
    """Handles a single character's turn in the fight.

    Processes status effects, applies hazards, chooses and performs an action,
    and handles end-of-turn cleanup.

    Args:
        character: The character whose turn it is.
        opponent: The opposing character.
        environment: The BaseEnvironment object.
        log_messages: List to append log messages to.

    Returns:
        True if the opponent was defeated during this turn, False otherwise.
    """
    opponent_defeated = False
    character.movement_points = character.DEFAULT_MOVEMENT

    status_log = character.process_status_effects()  # Get status log messages
    if status_log:
        log_messages.extend(status_log)

    # Check if conscious AFTER processing effects
    if not character.is_conscious():  # Check if conscious after status effects
        # log_messages might already contain stun message from process_status_effects
        return (
            False  # Character is stunned or otherwise incapacitated, opponent not defeated by this
        )

    # Check if character survived status effects
    if character.hp <= 0:
        # log_messages should already contain death message from process_status_effects
        # Opponent is the winner, but not defeated *this turn* by the current char's actions
        return False

    # Apply hazards based on current tile
    if isinstance(environment, BattleGrid):
        hazard_log = environment.apply_hazards(character)
        if hazard_log:
            log_messages.extend(hazard_log)
    # If not BattleGrid, maybe log a warning or have a base implementation?
    # else:
    #     log_messages.append(f"Warning: Hazard application not implemented for {type(environment).__name__}")

    if character.hp <= 0:
        # log_messages should already contain death message from apply_hazards
        # Opponent is the winner, but not defeated *this turn* by the current char's actions
        return False

    log_messages.append(
        f"{character.name}'s turn ({character.class_name.value}): HP={character.hp}/{character.max_hp}"
    )
    # Pass environment to AI
    action: Action = character.ai.choose_action(opponent, environment)
    # Pass log_messages list to _perform_action
    # Capture if the action defeated the opponent
    opponent_defeated = _perform_action(character, opponent, environment, action, log_messages)

    character.end_turn()
    return opponent_defeated  # Return if opponent was defeated by the action


def _perform_action(
    character: Character,
    opponent: Character,
    environment: BaseEnvironment,
    action: Action,
    log_messages: List[str],  # Add log_messages parameter
) -> bool:  # Changed return type to bool (opponent_defeated)
    """Performs the chosen action for the character.

    Args:
        character: The acting character.
        opponent: The opposing character.
        environment: The BaseEnvironment object.
        action: The Action enum member representing the action to perform.
        log_messages: List to append log messages to.

    Returns:
        True if the action resulted in the opponent's defeat, False otherwise.
    """
    opponent_defeated = False  # Initialize flag
    log_messages.append(f"  Action: {action.value}")

    if action == Action.ATTACK:
        opponent_defeated = _handle_attack_action(character, opponent, environment, log_messages)

    elif action == Action.MOVE:
        _handle_move_action(character, opponent, environment, log_messages)

    elif action == Action.DODGE:
        character.dodge()
        log_messages.append(f"  {character.name} takes the Dodge action.")

    elif action == Action.PARRY:
        character.parry()
        log_messages.append(f"  {character.name} takes the Parry action.")

    elif action == Action.USE_ITEM:
        opponent_defeated = _handle_item_action(character, opponent, log_messages)

    # Class-specific actions
    if not opponent_defeated and isinstance(character, Mage) and random.random() < 0.3:
        # Spellcasting doesn't currently interact with environment, but pass for consistency
        opponent_defeated = _handle_mage_spellcasting(character, opponent, log_messages)

    return opponent_defeated  # Return the defeat status


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
    character: Character, opponent: Character, environment: BaseEnvironment, log_messages: List[str]
) -> bool:  # Changed return type to bool (opponent_defeated)
    """Handles the attack action, calculates hit/miss/damage, and checks for winner.

    Checks weapon range, Line of Sight for ranged attacks, and cover bonuses.
    Applies appropriate stat bonuses based on weapon range.

    Args:
        character: The attacking character.
        opponent: The defending character.
        environment: The BaseEnvironment object.
        log_messages: List to append log messages to.

    Returns:
        True if the attack defeated the opponent, False otherwise.
    """
    attack_roll: float
    # Determine weapon range and if it's considered 'ranged' for LoS/Cover/Bonus checks
    weapon_range = character.weapon.get("range", 1.0)  # Default to 1.0 if missing
    is_effectively_ranged = weapon_range > 1.5  # Threshold for LoS/Cover/Dex bonus checks

    # Get character and opponent locations
    char_loc = environment.get_character_location(character)
    opp_loc = environment.get_character_location(opponent)

    if not char_loc or not opp_loc:
        log_messages.append(
            f"  Error: Cannot find location for {character.name} or {opponent.name}. Attack fails."
        )
        return False

    char_x, char_y = char_loc
    opp_x, opp_y = opp_loc

    distance = calculate_distance(char_x, char_y, opp_x, opp_y)

    # Set targeting line before checks
    if isinstance(environment, BattleGrid):
        environment.targeting_line = (char_loc, opp_loc)
    # We need to trigger a refresh here, but Live handles it
    # TODO: Consider adding a small delay or separate update step if needed

    # --- Range Check ---
    if distance > weapon_range:
        log_messages.append(
            f"  {character.name} is out of range! (Distance: {distance:.1f}, Range: {weapon_range:.1f})"
        )
        if isinstance(environment, BattleGrid):
            environment.targeting_line = None  # Clear targeting line
        return False

    # --- Attack Validity and Cover Checks ---
    target_ac_bonus_from_cover = 0
    can_attack = True
    if is_effectively_ranged:
        if not has_line_of_sight(char_x, char_y, opp_x, opp_y, environment):
            log_messages.append(f"  {character.name} has no Line of Sight to {opponent.name}!")
            can_attack = False
            if isinstance(environment, BattleGrid):
                environment.targeting_line = None  # Clear targeting line if LoS blocked
        else:
            # Check cover only if LoS exists for ranged attacks
            opp_tile = environment.get_tile(opp_x, opp_y)
            if opp_tile and opp_tile.provides_cover != CoverType.NONE:
                if opp_tile.provides_cover == CoverType.HALF:
                    target_ac_bonus_from_cover = 2
                    log_messages.append(f"  {opponent.name} benefits from Half Cover (+2 AC)")
                elif opp_tile.provides_cover == CoverType.FULL:
                    target_ac_bonus_from_cover = 5
                    log_messages.append(f"  {opponent.name} benefits from Full Cover (+5 AC)")

    if not can_attack:
        if isinstance(environment, BattleGrid):
            environment.targeting_line = None  # Clear if attack is not possible
        return False

    # --- Calculate Attack Roll and Target AC ---
    # Determine attribute bonus based on weapon type
    if is_effectively_ranged:
        # Calculate modifier directly
        attack_bonus = (character.dexterity - 10) // 2 + character.proficiency_bonus
    else:
        # Calculate modifier directly
        attack_bonus = (character.strength - 10) // 2 + character.proficiency_bonus

    attack_roll = random.randint(1, 20) + attack_bonus
    # Use opponent.ac for Armor Class
    target_ac = opponent.ac + target_ac_bonus_from_cover

    # --- Determine Hit/Miss ---
    if attack_roll >= target_ac:
        # Hit!
        # Calculate damage bonus modifier directly
        if is_effectively_ranged:
            damage_bonus = (character.dexterity - 10) // 2
        else:
            damage_bonus = (character.strength - 10) // 2

        # Revert to using the damage tuple from constants.py
        weapon_damage_range: Tuple[int, int] = character.weapon.get("damage", (1, 4))  # Default 1d4
        # Ensure it's a tuple of two integers
        if not (
            isinstance(weapon_damage_range, tuple)
            and len(weapon_damage_range) == 2
            and isinstance(weapon_damage_range[0], int)
            and isinstance(weapon_damage_range[1], int)
        ):
            log_messages.append(
                f"  Warning: Invalid weapon damage format {weapon_damage_range} for {character.name}. Using (1, 4)."
            )
            weapon_damage_range = (1, 4)

        # Ensure min <= max
        min_dmg, max_dmg = weapon_damage_range
        if min_dmg > max_dmg:
            log_messages.append(
                f"  Warning: Weapon min damage > max damage {weapon_damage_range}. Swapping."
            )
            min_dmg, max_dmg = max_dmg, min_dmg

        base_damage = random.randint(min_dmg, max_dmg)
        damage = max(0, base_damage + damage_bonus)  # Ensure non-negative damage

        # More detailed hit log
        log_messages.append(
            f"  {character.name} hits {opponent.name}! (Roll {attack_roll:.0f} vs AC {target_ac})"
        )
        log_messages.append(
            f"    Deals {damage} damage ({base_damage} base + {damage_bonus} bonus)."
        )
        if opponent.take_damage(damage):
            log_messages.append(f"    {opponent.name} has been defeated!")
            if isinstance(environment, BattleGrid):
                environment.targeting_line = None  # Clear after successful hit
            return True  # Opponent defeated
    else:
        # Miss!
        log_messages.append(
            f"  {character.name} misses {opponent.name}. (Roll {attack_roll:.0f} vs AC {target_ac})"
        )
        if isinstance(environment, BattleGrid):
            environment.targeting_line = None  # Clear after miss

    # Ensure targeting line is cleared if execution reaches here without returning
    if isinstance(environment, BattleGrid):
        environment.targeting_line = None

    return False  # Opponent not defeated by this attack


def _handle_move_action(
    character: Character, opponent: Character, environment: BaseEnvironment, log_messages: List[str]
) -> None:
    """Handles the move action, attempting to move the character on the grid.

    Uses the AI's direction choice and attempts movement one step at a time.
    Updates movement points consumed.

    Args:
        character: The moving character.
        opponent: The opposing character (needed for AI decision).
        environment: The BaseEnvironment object.
        log_messages: List to append log messages to.
    """
    steps_taken = 0
    max_steps = character.movement_points
    # Get initial location
    start_loc = environment.get_character_location(character)
    if not start_loc:
        log_messages.append(f"  Error: Cannot find {character.name} on the grid to move.")
        return
    start_x, start_y = start_loc

    # Loop for multiple steps within movement points
    while character.movement_points > 0:
        # Pass environment to AI for direction choice - CORRECT ORDER
        dx, dy = character.ai.choose_move_direction(environment, opponent)

        if dx == 0 and dy == 0:
            if steps_taken == 0:
                log_messages.append(f"  {character.name} decides not to move.")
            break  # Stop moving if AI decides to stay put

        # Calculate movement cost for the target tile
        current_loc = environment.get_character_location(character)
        if not current_loc:
            log_messages.append(f"  Error: {character.name}'s location lost mid-move.")
            break  # Safety break
        current_x, current_y = current_loc
        target_x, target_y = current_x + dx, current_y + dy
        target_tile = environment.get_tile(target_x, target_y)

        move_cost = 1  # Default cost
        if target_tile:
            move_cost = target_tile.movement_cost
        else:
            move_cost = 999  # Effectively impossible to move off-grid

        # Check if enough movement points
        if character.movement_points >= move_cost:
            if environment.move_character(character, dx, dy):
                character.movement_points -= move_cost
                steps_taken += 1
            else:
                # Move failed (blocked, occupied, off-grid)
                # AI might try a different direction next time if loop continues
                break  # Stop trying this path
        else:
            # Not enough points for this step
            break  # Stop moving

    end_loc = environment.get_character_location(character)
    if end_loc and (end_loc != start_loc):
        # Add movement cost detail if terrain is difficult
        start_tile = environment.get_tile(start_x, start_y)
        end_tile = environment.get_tile(end_loc[0], end_loc[1])
        cost_detail = ""
        # Simple check for difficult terrain, more complex tracking needed for exact cost per step
        if end_tile and end_tile.movement_cost > 1:
            cost_detail = f" (Entered difficult terrain)"
        log_messages.append(
            f"  {character.name} moves from {start_loc} to {end_loc} ({steps_taken} steps). {character.movement_points} MP left.{cost_detail}"
        )
    elif steps_taken > 0:
        log_messages.append(
            f"  {character.name} moved {steps_taken} steps. {character.movement_points} MP left."
        )


def _handle_item_action(
    character: Character, opponent: Character, log_messages: List[str]
) -> bool:  # Changed return type to bool (opponent_defeated)
    """Handles the Use Item action, allowing the character to use an item.

    Args:
        character: The character using the item.
        opponent: The opposing character (for potential targeting).
        log_messages: List to append log messages to.

    Returns:
        True if the item usage indirectly defeated the opponent, False otherwise.
    """
    item_to_use: Optional[ItemDict] = None
    # Simple logic: Use first usable item (e.g., Healing Potion if HP < max)
    for item in character.inventory:
        if item["type"] == "Healing Potion" and character.hp < character.max_hp:
            item_to_use = item
            break
        # Add more item logic here (e.g., throwing weapons)

    if item_to_use:
        use_result = character.use_item(item_to_use["name"])
        if use_result:
            # use_item should ideally return log messages itself
            # For now, assume it prints; add a placeholder log here
            log_messages.append(
                f"  {character.name} uses {item_to_use['name']}. Effect applied."
            )  # Adjusted log
            # Check if opponent defeated indirectly (e.g., reflected damage item - future?)
            # Check opponent HP directly after item use, as use_item doesn't know about opponent
            if opponent.hp <= 0:
                # Although the item didn't directly target, if the opponent is defeated now...
                log_messages.append(f"    (Item usage coincided with {opponent.name}'s defeat)")
                return True
        else:
            log_messages.append(f"  {character.name} failed to use {item_to_use['name']}.")
    else:
        log_messages.append(f"  {character.name} has no suitable item to use.")

    return False  # Assume item did not directly defeat opponent


def _handle_mage_spellcasting(
    mage: Mage, opponent: Character, log_messages: List[str]
) -> bool:  # Changed return type to bool (opponent_defeated)
    """Handles Mage spellcasting actions using the Mage.cast_spell method.

    Args:
        mage: The Mage character casting the spell.
        opponent: The opposing character.
        log_messages: List to append log messages to.

    Returns:
        True if the spell defeated the opponent, False otherwise.
    """
    available_spells = mage.get_available_spells()
    if not available_spells:
        log_messages.append(f"  {mage.name} has no spells available!")
        return False

    # Simple AI: Choose a random available spell
    # TODO: Improve AI spell choice based on situation (e.g., heal if low, buff if needed)
    chosen_spell_name = random.choice(available_spells)
    target = opponent  # Simple targetting for now

    # Use the new Mage.cast_spell method
    spell_result = mage.cast_spell(chosen_spell_name, target)

    if spell_result:
        # Added spell slot info to log
        log_messages.append(
            f"  {mage.name} casts {chosen_spell_name} (Slots: {mage.spell_slots}). {spell_result}"
        )
        # Check if the opponent was defeated by the spell's effect
        if opponent.hp <= 0:
            # Log message for defeat should be part of spell_result if it happened
            return True  # Opponent defeated
    else:
        # cast_spell should return a reason if it failed (e.g., no slots, already active)
        # If it returns None, it means something unexpected happened.
        # Added spell slot info to log
        log_messages.append(
            f"  {mage.name} failed to cast {chosen_spell_name} (Slots: {mage.spell_slots}). Reason unknown or invalid spell."
        )  # Adjusted log

    return False  # Opponent not defeated by this spell


def _determine_winner_post_loop(
    character1: Character, character2: Character, turn_count: int, max_turns: int
) -> str:
    """Determines the winner after the main fight loop concludes.

    Args:
        character1: The first character.
        character2: The second character.
        turn_count: The number of turns elapsed.
        max_turns: The maximum number of turns allowed.

    Returns:
        A string declaring the winner or the type of draw.
    """
    if character1.hp <= 0 and character2.hp <= 0:
        return "Draw (Mutual Destruction)"
    elif character1.hp <= 0:
        return character2.name
    elif character2.hp <= 0:
        return character1.name
    elif turn_count >= max_turns:
        return f"Draw (Reached Max Turns: {max_turns})"
    else:
        # Should not happen if loop logic is correct
        return "Draw (Unknown Reason)"


# flake8: noqa: C901
def fight(
    character1: Character, character2: Character, environment: BaseEnvironment
) -> str:  # Renamed parameter
    """Simulates a fight between two characters within a given environment.

    Uses rich.live for dynamic terminal display with log pane.

    Args:
        character1: The first character.
        character2: The second character.
        environment: The BaseEnvironment (or subclass like BattleGrid) for the fight.

    Returns:
        The name of the winner, or a description of the draw.
    """
    turn_count = 0
    max_turns = 100
    # winner: Optional[str] = None # Winner determined after the loop
    log_messages: List[str] = []

    # --- Rich Display Setup ---
    layout = create_layout()
    # Ensure combatants are correctly passed if needed by update_layout initially
    chars_on_grid = environment.get_characters()
    c1 = chars_on_grid[0] if len(chars_on_grid) > 0 else character1
    c2 = chars_on_grid[1] if len(chars_on_grid) > 1 else character2
    # --- End Rich Display Setup ---

    # --- REMOVED DEBUG: Print layout tree --- #
    # console.print("--- Layout Tree Before Live ---")
    # console.print(layout.tree)
    # console.print("--- End Layout Tree ---")
    # --- End REMOVED DEBUG ---

    # Use Live without screen=True or transient=True to persist display
    with Live(layout, refresh_per_second=4) as live:
        # Add initial log message AFTER Live starts
        log_messages.append(f"--- Fight: {character1.name} vs {character2.name} ---")
        # First update inside Live context
        update_layout(
            layout, environment, character1, character2, log_messages, f"Turn {turn_count+1}"
        )

        # --- Main Fight Loop --- #
        # Loop continues as long as both are alive and max turns not reached
        while character1.hp > 0 and character2.hp > 0 and turn_count < max_turns:
            turn_count += 1
            current_turn_logs: List[str] = []  # Logs specific to this turn
            status_msg = f"Turn {turn_count} / {max_turns}"
            # live.console.print(f"--- Turn {turn_count} ---") # No longer needed, log pane shows turns

            # Character 1's turn
            if character1.hp > 0:  # Check HP again in case of multi-hit hazards?
                _ = _handle_character_turn(  # We don't need the return value here anymore
                    character1, character2, environment, current_turn_logs
                )
                log_messages.extend(current_turn_logs)
                # Update display after char 1 turn
                update_layout(
                    layout,
                    environment,
                    character1,
                    character2,
                    log_messages,
                    status_msg + f" ({character1.name}'s turn end)",
                )
                # Check if opponent was defeated before proceeding
                if character2.hp <= 0:
                    break

            # Character 2's turn
            if character2.hp > 0:  # Check HP again
                current_turn_logs = []  # Reset for char 2
                _ = _handle_character_turn(  # Don't need return value
                    character2, character1, environment, current_turn_logs
                )
                log_messages.extend(current_turn_logs)
                # Update display after char 2 turn
                update_layout(
                    layout,
                    environment,
                    character1,
                    character2,
                    log_messages,
                    status_msg + f" ({character2.name}'s turn end)",
                )
                # Check if opponent was defeated before looping
                if character1.hp <= 0:
                    break

            # Removed winner check inside loop

        # --- Post-Loop Winner Determination and XP Handling --- #
        winner_name = _determine_winner_post_loop(character1, character2, turn_count, max_turns)
        final_status_msg = f"Fight Over! Winner: {winner_name}"
        log_messages.append(f"--- {final_status_msg} ---")

        # Award XP and add log messages
        xp_messages = []
        if (
            winner_name != "Draw"
            and winner_name != "Draw (Mutual Destruction)"
            and not winner_name.startswith("Draw")
        ):
            winner_char = character1 if winner_name == character1.name else character2
            loser = character2 if winner_name == character1.name else character1
            # Use a default XP gain or calculate based on loser level etc.
            xp_gain = 100  # Default for now, adjust as needed
            xp_messages = winner_char.gain_xp(xp_gain)
            log_messages.extend(xp_messages)
        elif winner_name.startswith("Draw"):
            log_messages.append("No XP awarded for a Draw.")

        # Ensure the final log message is added before exiting Live context - Moved above XP
        # final_status_msg = f"Fight Over! Winner: {winner_name}"
        # log_messages.append(f"--- {final_status_msg} ---")  # Add final status to log

        # Perform one last update to show the final state including winner AND XP in log
        update_layout(layout, environment, character1, character2, log_messages, final_status_msg)

    # Final status panel is printed in simulation.py after Live exits - Comment inaccurate

    return winner_name  # Return the determined winner name
