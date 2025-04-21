"""Base class and core functionality for characters in the simulation."""

import random
from typing import List, Optional, Tuple

from ..constants import ARMORS, INITIAL_ITEMS, WEAPONS
from ..datatypes import ArmorDict, ItemDict, StatusEffectDict, WeaponDict

# Import Enums, Constants, Datatypes
from ..enums import CharacterClass, ItemType, Personality, StatusEffect

# Import AI class - Moved inside __init__ to avoid circular import
# from .ai import CombatAI

# Forward reference for BattleGrid - Not actually used in this file currently
# if TYPE_CHECKING:
#     from ..environment import BattleGrid


class Character:
    """Represents a base character in the simulation.

    Attributes:
        name: The character's name.
        strength: Strength attribute, affecting melee damage.
        dexterity: Dexterity attribute, affecting AC and ranged attacks.
        constitution: Constitution attribute, affecting HP.
        hp: Current hit points.
        weapon: Dictionary representing the character's equipped weapon.
        armor: Dictionary representing the character's equipped armor.
        ac: Armor Class, the target number for attacks to hit.
        level: Character's current level.
        xp: Current experience points.
        xp_to_next_level: XP needed to reach the next level.
        status_effects: A list of currently active status effect dictionaries.
        inventory: A list of item dictionaries the character possesses.
        personality: The character's AI personality ('aggressive', 'cautious', 'tactical').
        ai: The CombatAI instance controlling this character.
        class_name: The CharacterClass Enum member.
        max_hp: Maximum hit points.
    """

    # Default movement can be adjusted by subclasses or based on stats - Removed class attribute
    # DEFAULT_MOVEMENT: int = 5

    def __init__(self, name: str) -> None:
        """Initializes a new Character with random stats, weapon, and armor.

        Args:
            name: The name of the character.
        """
        self.name: str = name
        # Define DEFAULT_MOVEMENT as an instance attribute early
        self.DEFAULT_MOVEMENT: int = 5
        self.strength: int = random.randint(8, 18)
        self.dexterity: int = random.randint(8, 18)
        self.constitution: int = random.randint(8, 18)
        self.max_hp: int = self.constitution * 2  # Define max_hp based on constitution
        self.hp: int = self.max_hp  # Start at full health
        self.weapon: WeaponDict = random.choice(WEAPONS)
        self.armor: ArmorDict = random.choice(ARMORS)
        self.ac: int = 10 + (self.dexterity - 10) // 2 + self.armor.get("ac_bonus", 0)
        self.level: int = 1
        self.xp: int = 0
        self.xp_to_next_level: int = 100
        self.status_effects: List[StatusEffectDict] = []
        self.inventory: List[ItemDict] = random.sample(INITIAL_ITEMS, k=min(len(INITIAL_ITEMS), 2))
        self.personality: Personality = random.choice(list(Personality))
        # Import CombatAI here to avoid circular dependency at module level
        from .ai import CombatAI

        self.ai: CombatAI = CombatAI(self, self.personality)
        self.class_name: CharacterClass = CharacterClass.BASE
        # Now set movement_points using the instance attribute
        self.movement_points: int = self.DEFAULT_MOVEMENT

    @property
    def proficiency_bonus(self) -> int:
        """Calculates the proficiency bonus based on character level."""
        # Standard 5e proficiency bonus progression
        return (self.level - 1) // 4 + 2

    def get_display_char(self) -> str:
        """Returns the character to display on the grid (first letter of name)."""
        return self.name[0].upper() if self.name else "?"

    def perform_attack_roll(self, ranged: bool) -> float:
        """Calculates the d20 roll for an attack, adding appropriate bonuses.

        Handles critical hits (20) and misses (1).
        Uses Strength bonus for melee, Dexterity bonus for ranged.

        Args:
            ranged: True if the attack is ranged, False if melee.

        Returns:
            The result of the attack roll (float), float('inf') for a critical hit,
            or float('-inf') for a critical miss.
        """
        roll: int = random.randint(1, 20)
        if roll == 20:
            print(f"Critical hit by {self.name}!")
            return float("inf")  # Guarantee a hit
        elif roll == 1:
            print(f"Critical miss by {self.name}!")
            return float("-inf")  # Guarantee a miss

        if ranged:
            bonus = (self.dexterity - 10) // 2
        else:
            bonus = (self.strength - 10) // 2

        return float(roll + bonus)

    def deal_damage(self) -> int:
        """Calculates the base damage dealt by a weapon attack.

        Note: Stat bonus (STR/DEX) is now added in the combat logic based on range.
        Crit bonus is also handled in combat logic.

        Returns:
            The base amount of damage dealt (integer).
        """
        base_damage: int = random.randint(self.weapon["damage"][0], self.weapon["damage"][1])
        # Damage bonus (STR/DEX) is now handled in combat.py
        # damage: int = base_damage + (self.strength - 10) // 2
        return max(0, base_damage)  # Ensure non-negative damage

    def dodge(self) -> None:
        """Increases AC temporarily for a defensive stance."""
        # TODO: Implement temporary AC boost properly (e.g., via a status effect or temp attribute)
        # self.ac += 2
        print(f"{self.name} takes a defensive stance. AC increased by 2 for this turn.")

    def parry(self) -> int:
        """Prepares to parry, imposing a penalty on the next attack roll against them.

        Returns:
            The parry bonus (penalty to attacker's roll).
        """
        parry_bonus: int = (self.dexterity - 10) // 2
        # TODO: Implement parry effect properly (e.g., via status effect/temp attribute)
        print(
            f"{self.name} prepares to parry. Next attack against them has a -{parry_bonus} penalty."
        )
        return parry_bonus  # Returning bonus, but combat logic doesn't use it yet

    def use_item(self) -> Optional[ItemDict]:
        """Uses a random item from the inventory.

        Handles healing items and potentially damage items (returning the item).
        Removes the used item from inventory.

        Returns:
            The item dictionary if it's a damage item, None otherwise.
        """
        if not self.inventory:
            print(f"{self.name} has no items to use.")
            return None

        item: ItemDict = random.choice(self.inventory)
        item_type_str: str = item.get("type", ItemType.UNKNOWN.value)
        item_name: str = item.get("name", "Unknown Item")
        self.inventory.remove(item)  # Consume the item

        try:
            item_type: ItemType = ItemType(item_type_str)
        except ValueError:
            item_type = ItemType.UNKNOWN

        if item_type == ItemType.HEALING:
            heal_range: Tuple[int, int] = item.get("heal", (0, 0))
            heal_amount: int = random.randint(heal_range[0], heal_range[1])
            self.hp += heal_amount
            print(f"{self.name} uses {item_name} and heals for {heal_amount} HP.")
            return None  # Healing item consumed, doesn't return for damage logic
        elif item_type == ItemType.DAMAGE:
            # Return the item for the fight logic to handle damage
            print(f"{self.name} prepares to use {item_name}...")
            return item
        else:  # Unknown type
            print(
                f"{self.name} tries to use {item_name}, but it has an unknown type ({item_type_str})."
            )
            return None

    def apply_status_effect(self, effect: StatusEffectDict) -> None:
        """Applies a status effect to the character.

        Args:
            effect: A dictionary describing the status effect (e.g., name, duration).
        """
        effect_name_str = effect.get("name", StatusEffect.UNKNOWN.value)
        try:
            _ = StatusEffect(effect_name_str)  # Check if name is valid enum member
            self.status_effects.append(effect.copy())  # Append a copy to avoid mutation issues
            print(f"{self.name} is now {effect_name_str}.")
        except ValueError:
            print(f"Warning: Tried to apply unknown status effect '{effect_name_str}'.")

    def process_status_effects(self) -> List[str]:
        """Processes active status effects at the start of the turn.

        Applies damage for poison, checks for stun, and decrements durations.
        Removes expired effects.

        Returns:
            A list of log messages generated during status effect processing.
            Note: The character's ability to act (e.g., due to stun) needs to be checked
            separately using is_conscious() after calling this method.
        """
        # can_act = True # NOTE: can_act is currently unused, logic relies on is_conscious()
        logs = []  # Initialize logs list
        effects_to_keep: List[StatusEffectDict] = []
        for effect in self.status_effects:
            effect_name_str = effect.get("name", StatusEffect.UNKNOWN.value)
            duration = effect.get("duration", 0)

            try:
                effect_type = StatusEffect(effect_name_str)
            except ValueError:
                logs.append(f"Warning: Processing unknown status effect '{effect_name_str}'")
                continue  # Skip unknown effects

            if effect_type == StatusEffect.POISONED:
                damage = random.randint(1, 4)  # Example poison damage
                self.hp -= damage
                logs.append(f"{self.name} takes {damage} damage from poison.")
                if self.hp <= 0:
                    logs.append(f"{self.name} succumbed to poison!")
                    # Don't immediately return, process other effects first

            if effect_type == StatusEffect.STUNNED:
                # can_act = False # Character cannot act this turn - Handled by is_conscious()
                logs.append(f"{self.name} is stunned and cannot act.")

            # Decrement duration and check for expiry
            duration -= 1
            if duration > 0:
                effect["duration"] = duration
                effects_to_keep.append(effect)
            else:
                logs.append(f"{self.name} is no longer {effect_name_str}.")

        self.status_effects = effects_to_keep
        # Return logs. The caller should check character.is_conscious() separately.
        return logs

    def is_conscious(self) -> bool:
        """Checks if the character is able to act (not stunned, etc.)."""
        for effect in self.status_effects:
            effect_name_str = effect.get("name", StatusEffect.UNKNOWN.value)
            if effect_name_str == StatusEffect.STUNNED.value:
                return False
        return True

    def end_turn(self) -> None:
        """Performs end-of-turn cleanup for the character."""
        # Placeholder for effects that might expire at end of turn
        # For now, just resets temporary flags/bonuses (if any were implemented)
        pass  # Example: self.ac -= temp_ac_bonus; self.temp_ac_bonus = 0

    def take_damage(self, damage: int) -> bool:
        """Applies damage to the character's HP.

        Args:
            damage: The amount of damage to take.

        Returns:
            True if the character was defeated (HP <= 0), False otherwise.
        """
        self.hp -= damage
        # print(f"{self.name} takes {damage} damage. HP: {self.hp}") # Handled by logs now
        return self.hp <= 0

    def gain_xp(self, amount: int) -> List[str]:
        """Adds experience points and checks for level up.

        Args:
            amount: The amount of XP to gain.

        Returns:
            A list of log messages generated (XP gain, level up).
        """
        log_messages = []
        self.xp += amount
        # print(f"{self.name} gains {amount} XP.")  # Remove print
        log_messages.append(f"{self.name} gains {amount} XP.")  # Add to list
        if self.xp >= self.xp_to_next_level:
            level_up_message = self.level_up()  # Capture message
            log_messages.append(level_up_message)  # Add level up message
        return log_messages

    def level_up(self) -> str:
        """Handles the character leveling up.

        Increases level, resets XP, increases XP threshold, and boosts stats.

        Returns:
            A log message describing the level up.
        """
        self.level += 1
        self.xp -= self.xp_to_next_level
        self.xp_to_next_level = int(self.xp_to_next_level * 1.5)  # Increase XP needed

        # Increase stats (example: +1 to a random stat, +2 constitution for HP)
        stat_increase_choice = random.choice(["strength", "dexterity", "constitution"])
        setattr(self, stat_increase_choice, getattr(self, stat_increase_choice) + 1)
        self.constitution += 2

        # Recalculate max HP and heal fully
        self.max_hp = self.constitution * 2
        self.hp = self.max_hp

        # Recalculate AC based on new stats/potential armor changes (if any)
        self.ac = 10 + (self.dexterity - 10) // 2 + self.armor.get("ac_bonus", 0)

        # print(f"{self.name} leveled up to Level {self.level}! Stats increased.")  # Remove print
        return f"{self.name} leveled up to Level {self.level}! Stats increased."  # Return message

    def __str__(self) -> str:
        """Returns a string representation of the character."""
        return (
            f"{self.name} ({self.class_name.value} L{self.level}) - "
            f"HP: {self.hp}/{self.max_hp}, AC: {self.ac}  "
            f"Weapon: {self.weapon.get('name', 'None')}, "
            f"Armor: {self.armor.get('name', 'None')}  "
            f"Stats: STR {self.strength}, DEX {self.dexterity}, CON {self.constitution}, "
            f"Inv: {[item['name'] for item in self.inventory]}"
        )
