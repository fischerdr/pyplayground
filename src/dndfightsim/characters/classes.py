"""Defines specific character classes inheriting from the base Character."""

import random
from typing import TYPE_CHECKING, Optional, Tuple

from ..constants import DEFENSIVE_SPELLS, OFFENSIVE_SPELLS
from ..datatypes import SpellDict
from ..enums import CharacterClass

# Import Base Class and Enums/Constants/Datatypes
from .base import Character

# Forward reference for BattleGrid
if TYPE_CHECKING:
    from ..environment import BattleGrid


class Warrior(Character):
    """Represents a Warrior character class."""

    def __init__(self, name: str) -> None:
        """Initializes a Warrior.

        Args:
            name: The name of the character.
        """
        super().__init__(name)
        self.class_name = CharacterClass.WARRIOR


class Mage(Character):
    """Represents a Mage character class with spellcasting abilities.

    Attributes:
        spell_slots: Number of spells the Mage can cast.
        active_defense_spell: The currently active defensive spell dictionary, if any.
        defense_spell_duration: Remaining duration for the active defensive spell.
    """

    def __init__(self, name: str) -> None:
        """Initializes a Mage.

        Args:
            name: The name of the character.
        """
        super().__init__(name)
        self.class_name = CharacterClass.MAGE
        self.spell_slots: int = 3
        self.active_defense_spell: Optional[SpellDict] = None
        self.defense_spell_duration: int = 0

    def cast_offensive_spell(self) -> Tuple[Optional[str], int]:
        """Casts a random offensive spell if spell slots are available.

        Returns:
            A tuple (spell_name, damage) if cast, or (None, 0) otherwise.
        """
        if self.spell_slots > 0:
            spell: SpellDict = random.choice(OFFENSIVE_SPELLS)
            self.spell_slots -= 1
            damage_range: Tuple[int, int] = spell.get("damage", (0, 0))
            damage: int = random.randint(damage_range[0], damage_range[1])
            return spell.get("name"), damage
        return None, 0

    def cast_defensive_spell(self) -> int:
        """Casts a random defensive spell if spell slots are available.

        Handles Shield (AC bonus) and Healing Light (HP restore).

        Returns:
            The amount healed or AC bonus applied, 0 otherwise.
        """
        if self.spell_slots > 0:
            spell: SpellDict = random.choice(DEFENSIVE_SPELLS)
            self.spell_slots -= 1
            spell_name: str = spell.get("name", "Unknown Spell")

            if "ac_bonus" in spell:
                if self.active_defense_spell and self.active_defense_spell["name"] == spell_name:
                    print(f"{self.name} tries to cast {spell_name}, but it's already active.")
                    self.spell_slots += 1  # Don't consume slot if already active
                    return 0

                if self.active_defense_spell:
                    # Remove old bonus before applying new one
                    self.ac -= self.active_defense_spell.get("ac_bonus", 0)

                self.active_defense_spell = spell
                self.defense_spell_duration = spell.get("duration", 0)
                ac_bonus = spell.get("ac_bonus", 0)
                self.ac += ac_bonus
                print(
                    f"{self.name} casts {spell_name}, gaining +{ac_bonus} AC for {self.defense_spell_duration} turns."
                )
                return ac_bonus
            elif "heal" in spell:
                heal_range: Tuple[int, int] = spell.get("heal", (0, 0))
                heal_amount: int = random.randint(heal_range[0], heal_range[1])
                self.hp += heal_amount
                print(f"{self.name} casts {spell_name} and heals {heal_amount} HP!")
                return heal_amount
        return 0

    def end_turn(self) -> None:
        """Mage-specific end-of-turn logic, handling spell durations."""
        super().end_turn()  # Call base class end_turn first

        # Handle active defense spell duration and AC adjustment
        if self.active_defense_spell:
            self.defense_spell_duration -= 1
            ac_bonus = self.active_defense_spell.get("ac_bonus", 0)
            if self.defense_spell_duration <= 0:
                print(f"{self.name}'s {self.active_defense_spell['name']} wears off.")
                # self.ac -= ac_bonus # AC reset is handled by super().end_turn()
                # ac_bonus_removed = ac_bonus # Unused variable
                self.active_defense_spell = None
            else:
                # If spell is still active, re-apply AC bonus after base reset
                self.ac += ac_bonus


class Ranger(Character):
    """Represents a Ranger character class, skilled in ranged combat."""

    def __init__(self, name: str) -> None:
        """Initializes a Ranger.

        Args:
            name: The name of the character.
        """
        super().__init__(name)
        self.class_name = CharacterClass.RANGER

    def ranged_attack(self, target: "Character", battle_grid: "BattleGrid") -> float:
        """Calculates the roll for a ranged attack.

        Args:
            target: The target Character object.
            battle_grid: The BattleGrid object.

        Returns:
            The result of the attack roll (float).
        """
        # Ranger calls the base Character ranged_attack which includes cover check.
        print(f"({self.class_name.value} uses Dexterity for ranged attack roll)")
        return super().ranged_attack(target, battle_grid)

    def deal_damage(self) -> int:
        """Calculates damage for an attack, using Dexterity for ranged bonus.

        Note: This assumes the Ranger always uses ranged attacks for bonus.
        A better approach would check the weapon type.

        Returns:
            The amount of damage dealt (integer).
        """
        base_damage: int = random.randint(self.weapon["damage"][0], self.weapon["damage"][1])
        # Use Dexterity bonus for damage instead of Strength
        damage: int = base_damage + (self.dexterity - 10) // 2
        # TODO: Check for critical hit properly
        return max(0, damage)


class Rogue(Character):
    """Represents a Rogue character class with sneak attack ability.

    Attributes:
        # Removed sneak_attack_damage_multiplier as logic changed
    """

    def __init__(self, name: str) -> None:
        """Initializes a Rogue.

        Args:
            name: The name of the character.
        """
        super().__init__(name)
        self.class_name = CharacterClass.ROGUE
        # self.sneak_attack_damage_multiplier: int = 2 # Removed

    def _calculate_sneak_attack_damage(self) -> int:
        """Calculates bonus damage dice for a sneak attack based on level."""
        num_dice = (self.level + 1) // 2  # Example: 1d6 L1-2, 2d6 L3-4, etc.
        bonus_damage = sum(random.randint(1, 6) for _ in range(num_dice))
        print(f"...adds {bonus_damage} sneak attack damage ({num_dice}d6)!")
        return bonus_damage

    def deal_damage(self) -> int:
        """Calculates damage, adding sneak attack bonus if applicable.

        Placeholder condition: 20% chance for sneak attack.
        TODO: Implement proper sneak attack conditions (e.g., advantage, ally adjacent).
        """
        base_weapon_damage = super().deal_damage()  # Get base damage (STR bonus)

        # Check for sneak attack conditions (placeholder: random chance)
        if random.random() < 0.2:  # TODO: Replace with real condition check
            sneak_bonus = self._calculate_sneak_attack_damage()
            return base_weapon_damage + sneak_bonus
        else:
            return base_weapon_damage
