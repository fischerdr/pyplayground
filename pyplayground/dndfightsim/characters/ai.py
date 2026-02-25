"""Defines the AI logic for controlling characters in combat."""

import random

# import math # Added for distance calculation - Unused
from typing import TYPE_CHECKING, List, Optional, Tuple

from ..combat import calculate_distance, has_line_of_sight  # Import LoS and distance
from ..datatypes import Coordinate
from ..enums import Action, CoverType, Personality

# Needs BaseEnvironment and Character imports
if TYPE_CHECKING:
    # Use forward references or actual imports later
    from ..environment import BaseEnvironment  # Changed from BattleGrid
    from .base import Character

    # from .classes import Ranger # Removed unused top-level import


class CombatAI:
    """Provides simple AI decision-making for characters in combat.

    Attributes:
        character: The Character object this AI controls.
        personality: The AI's personality ('aggressive', 'cautious', 'tactical'),
                     which influences action choices.
    """

    def __init__(self, character: "Character", personality: Personality) -> None:
        """Initializes the CombatAI.

        Args:
            character: The Character object the AI will control.
            personality: The personality type ('aggressive', 'cautious', 'tactical').
        """
        self.character: "Character" = character
        self.personality: Personality = personality

    def choose_action(self, opponent: "Character", environment: "BaseEnvironment") -> Action:
        """Chooses a combat action based on weights.

        Args:
            opponent: The opposing Character object.
            environment: The BaseEnvironment object representing the combat area.

        Returns:
            An Action enum member representing the chosen action.
        """
        actions: List[Action] = list(Action)
        weights: List[float] = self.calculate_action_weights(opponent, environment)
        chosen_action: Action = random.choices(actions, weights=weights)[0]
        return chosen_action

    # flake8: noqa: C901
    def calculate_action_weights(self, opponent: "Character", environment: "BaseEnvironment") -> List[float]:
        """Calculates weights for different actions based on personality and situation.

        Considers Line of Sight, cover, and adjacency for attacks.

        Args:
            opponent: The opposing Character object.
            environment: The BaseEnvironment object.

        Returns:
            A list of weights corresponding to the actions:
            [attack, move, dodge, parry, use_item].
        """
        # Initial weights: Attack=1.5, Move=1.0, Dodge=1.0, Parry=0.8, UseItem=1.0
        weights: List[float] = [1.5, 1.0, 1.0, 0.8, 1.0]  # Base weights adjusted
        attack_possible = False
        attack_idx = list(Action).index(Action.ATTACK)
        move_idx = list(Action).index(Action.MOVE)
        dodge_idx = list(Action).index(Action.DODGE)
        parry_idx = list(Action).index(Action.PARRY)
        item_idx = list(Action).index(Action.USE_ITEM)

        # --- Get Locations and Distance ---
        char_loc: Optional[Coordinate] = environment.get_character_location(self.character)
        opp_loc: Optional[Coordinate] = environment.get_character_location(opponent)

        if not char_loc or not opp_loc:  # Handle case where character location is unknown
            print("Warning: Could not determine location for AI weight calculation.")
            weights[attack_idx] = 0.1  # Heavily discourage attack if location unknown
            return weights

        char_x, char_y = char_loc
        opp_x, opp_y = opp_loc
        distance = calculate_distance(char_x, char_y, opp_x, opp_y)

        # --- Check Attack Possibility ---
        weapon_range_type = self.character.weapon.get("range_type", "melee")
        target_has_cover = False
        target_cover_type = CoverType.NONE

        if weapon_range_type == "ranged":
            if has_line_of_sight(char_x, char_y, opp_x, opp_y, environment):
                attack_possible = True
                target_tile = environment.get_tile(opp_x, opp_y)
                if target_tile and target_tile.provides_cover != CoverType.NONE:
                    target_has_cover = True
                    target_cover_type = target_tile.provides_cover
            # else: Ranged attack not possible (LoS blocked)
        else:  # Melee
            if distance <= 1.5:
                attack_possible = True
            # else: Melee attack not possible (too far)

        # --- Adjust Weights Based on Personality ---
        if self.personality == Personality.AGGRESSIVE:
            weights[attack_idx] *= 2.0 if attack_possible else 0.1  # Further increase aggressive attack
            weights[move_idx] *= 1.5  # Encourage closing distance
            weights[dodge_idx] *= 0.5  # Aggressive less likely to dodge
            weights[parry_idx] *= 0.3  # Aggressive very unlikely to parry
        elif self.personality == Personality.CAUTIOUS:
            weights[dodge_idx] *= 1.5
            weights[parry_idx] *= 1.2  # Cautious might parry more
            weights[attack_idx] *= 0.6  # Further decrease cautious attack likelihood
            weights[move_idx] *= 0.8  # Less likely to move into danger
        elif self.personality == Personality.TACTICAL:
            weights[move_idx] *= 1.5  # Tactical AI likes positioning
            weights[item_idx] *= 1.5
            if target_has_cover:
                weights[attack_idx] *= 0.5  # Tactical AI avoids shooting into cover

        # --- Adjust Weights Based on Situation ---
        # Attack weight adjustment
        if attack_possible:
            if target_has_cover:
                # General penalty for cover, tactical already penalized
                if self.personality != Personality.TACTICAL:
                    weights[attack_idx] *= 0.7
                if target_cover_type == CoverType.THREE_QUARTERS:
                    weights[attack_idx] *= 0.5  # Heavy penalty for 3/4 cover
        else:
            weights[attack_idx] *= 0.1  # Heavily penalize if attack impossible
            weights[move_idx] *= 3.0  # STRONGLY Encourage moving if cannot attack

        # Move weight adjustment (general)
        if distance > 5:  # If quite far away, really want to move
            weights[move_idx] *= 1.5
        elif distance <= 1.5 and weapon_range_type == "ranged":  # Ranged character too close
            weights[move_idx] *= 1.5  # Encourage moving away

        # Item weight adjustment
        if self.character.hp < self.character.constitution * 0.5:  # Low health threshold
            weights[item_idx] *= 2.0  # More likely to use items when low on health
            weights[dodge_idx] *= 1.5  # Also more likely to be defensive when low
            weights[parry_idx] *= 1.5  # Parry is also defensive

        # Cover benefit for self
        own_tile = environment.get_tile(char_x, char_y)
        if own_tile and own_tile.provides_cover != CoverType.NONE:
            weights[attack_idx] *= 1.2  # Slight bonus to attack from cover
            weights[dodge_idx] *= 0.8  # Less need to dodge if in cover
            weights[parry_idx] *= 0.8  # Less need to parry if in cover

        # Ensure weights are not negative
        weights = [max(0.01, w) for w in weights]  # Ensure a small chance for all actions

        return weights

    def _get_initial_move_direction(self, char_loc: Coordinate, opp_loc: Coordinate, environment: "BaseEnvironment") -> Tuple[int, int]:
        """Determines the initial move direction based on personality."""
        char_x, char_y = char_loc
        opp_x, opp_y = opp_loc

        if self.personality == Personality.AGGRESSIVE:
            # Move towards opponent
            dx = 1 if opp_x > char_x else -1 if opp_x < char_x else 0
            dy = 1 if opp_y > char_y else -1 if opp_y < char_y else 0
            # If already adjacent for melee, consider staying put unless ranged?
            is_melee = self.character.weapon.get("range_type", "melee") == "melee"
            if is_melee and calculate_distance(char_x, char_y, opp_x, opp_y) <= 1.5:
                dx, dy = 0, 0  # Stay put if adjacent and melee

        elif self.personality == Personality.CAUTIOUS:
            # Move away from opponent IF close
            if calculate_distance(char_x, char_y, opp_x, opp_y) <= 1.5:
                dx = -1 if opp_x > char_x else 1 if opp_x < char_x else 0
                dy = -1 if opp_y > char_y else 1 if opp_y < char_y else 0
            else:
                # Find tiles providing cover
                cover_tiles: List[Coordinate] = []
                for y in range(environment.height):
                    for x in range(environment.width):
                        tile = environment.get_tile(x, y)
                        if tile and tile.provides_cover != CoverType.NONE:  # Check enum value
                            cover_tiles.append((x, y))

                if cover_tiles:
                    # Find nearest cover tile
                    target_x, target_y = min(cover_tiles, key=lambda pos: (pos[0] - char_x) ** 2 + (pos[1] - char_y) ** 2)
                    # If already in cover, maybe don't move?
                    current_tile = environment.get_tile(char_x, char_y)
                    if current_tile and current_tile.provides_cover != CoverType.NONE:
                        dx, dy = 0, 0  # Stay if already in cover
                    else:
                        # Move towards nearest cover
                        dx = 1 if target_x > char_x else -1 if target_x < char_x else 0
                        dy = 1 if target_y > char_y else -1 if target_y < char_y else 0
                else:
                    # No cover, move towards opponent slightly less directly than aggressive
                    # Or maintain optimal range if ranged?
                    # Simple approach: move towards opponent if far, random if close
                    if calculate_distance(char_x, char_y, opp_x, opp_y) > 3.0:
                        dx = 1 if opp_x > char_x else -1 if opp_x < char_x else 0
                        dy = 1 if opp_y > char_y else -1 if opp_y < char_y else 0
                    else:
                        dx, dy = random.choice([(0, 1), (0, -1), (1, 0), (-1, 0), (0, 0)])  # Add stay put option
        else:  # Tactical
            # Find tiles providing cover
            cover_tiles: List[Coordinate] = []
            for y in range(environment.height):
                for x in range(environment.width):
                    tile = environment.get_tile(x, y)
                    if tile and tile.provides_cover != CoverType.NONE:  # Check enum value
                        cover_tiles.append((x, y))

            if cover_tiles:
                # Find nearest cover tile
                target_x, target_y = min(cover_tiles, key=lambda pos: (pos[0] - char_x) ** 2 + (pos[1] - char_y) ** 2)
                dx = 1 if target_x > char_x else -1 if target_x < char_x else 0
                dy = 1 if target_y > char_y else -1 if target_y < char_y else 0
            else:
                # No cover, move randomly
                dx, dy = random.choice([(0, 1), (0, -1), (1, 0), (-1, 0)])
        return dx, dy

    def _is_move_valid(self, x: int, y: int, environment: "BaseEnvironment") -> bool:
        """Checks if a potential move coordinate is valid."""
        target_tile = environment.get_tile(x, y)
        return target_tile is not None and not target_tile.blocks_movement and target_tile.character is None

    def _find_random_valid_move(self, char_loc: Coordinate, environment: "BaseEnvironment") -> Tuple[int, int]:
        """Finds a random valid move direction if the initial choice is blocked."""
        char_x, char_y = char_loc
        possible_moves = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        random.shuffle(possible_moves)
        for rdx, rdy in possible_moves:
            if self._is_move_valid(char_x + rdx, char_y + rdy, environment):
                return rdx, rdy
        return 0, 0  # No valid move found, stay put

    def choose_move_direction(self, environment: "BaseEnvironment", opponent: "Character") -> Tuple[int, int]:
        """Determines the final direction to move based on personality and situation.

        Args:
            environment: The BaseEnvironment object.
            opponent: The opposing Character object.

        Returns:
            A tuple (dx, dy) representing the chosen move direction.
        """
        char_loc = environment.get_character_location(self.character)
        opp_loc = environment.get_character_location(opponent)

        if not char_loc or not opp_loc:
            print("Warning: Could not determine location for AI move calculation. Staying put.")
            return (0, 0)

        char_x, char_y = char_loc

        # 1. Get initial direction based on personality
        dx, dy = self._get_initial_move_direction(char_loc, opp_loc, environment)

        # 2. Check if the initial move is valid
        new_x, new_y = char_x + dx, char_y + dy
        if not self._is_move_valid(new_x, new_y, environment):
            # If chosen move is invalid, find a random valid move
            dx, dy = self._find_random_valid_move(char_loc, environment)

        # 3. Consider adjusting move based on target tile properties (cover/hazard)
        # This part might need more complex logic depending on desired behavior
        # For now, keep it simple or comment out if not fully implemented
        final_target_tile = environment.get_tile(char_x + dx, char_y + dy)

        # Check for cover (use CoverType enum) - Example adjustment logic
        # if final_target_tile and final_target_tile.provides_cover != CoverType.NONE:  # Check enum value
        #     pass # Maybe prioritize staying if already moving to cover?

        # Check for hazards (use Tile attribute) - Example adjustment logic
        # if final_target_tile and final_target_tile.hazard:
        #     # Maybe try to find a *different* valid move if this one leads into a hazard?
        #     pass

        return dx, dy
