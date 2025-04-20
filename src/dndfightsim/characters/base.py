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
        self.hp: int = self.constitution * 2
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

    def process_status_effects(self) -> bool:
        """Processes active status effects at the start of the turn.

        Applies damage for poison, checks for stun, and decrements durations.
        Removes expired effects.

        Returns:
            True if the character can take their turn, False if stunned.
        """
        can_act = True
        effects_to_keep: List[StatusEffectDict] = []
        for effect in self.status_effects:
            effect_name_str = effect.get("name", StatusEffect.UNKNOWN.value)
            duration = effect.get("duration", 0)
            effect_name: StatusEffect
            try:
                effect_name = StatusEffect(effect_name_str)
            except ValueError:
                effect_name = StatusEffect.UNKNOWN

            if effect_name == StatusEffect.POISONED:
                damage = random.randint(1, 4)
                print(f"{self.name} takes {damage} poison damage.")
                if self.take_damage(damage):
                    print(f"{self.name} succumbed to poison!")
                    # No need to set can_act = False here, death is handled in main loop
            elif effect_name == StatusEffect.STUNNED:
                print(f"{self.name} is stunned and loses their turn.")
                can_act = False  # Stunned characters lose their action
            elif effect_name == StatusEffect.UNKNOWN:
                print(
                    f"Warning: Processing unknown status effect '{effect_name_str}' on {self.name}."
                )

            duration -= 1
            if duration > 0:
                effect["duration"] = duration  # Update duration in the original dict
                effects_to_keep.append(effect)
            else:
                print(f"{self.name} is no longer {effect_name_str}.")

        self.status_effects = effects_to_keep
        return can_act

    def end_turn(self) -> None:
        """Resets temporary effects like AC bonuses from dodging."""
        # Reset AC based on base AC + armor, potential spells will modify this further
        base_ac = 10 + (self.dexterity - 10) // 2 + self.armor.get("ac_bonus", 0)
        # TODO: Properly handle temporary AC changes (Dodge/Parry/Spells)
        # If AC was boosted by Dodge, reset it. Mage handles its own spells.
        # Need a better way to track temporary AC boosts vs spell boosts.
        # For now, just reset to base + armor.
        self.ac = base_ac
        # Mage subclass will handle resetting/reapplying spell AC bonus

    def take_damage(self, damage: int) -> bool:
        """Applies damage to the character's HP.

        Args:
            damage: The amount of damage to take.

        Returns:
            True if the damage reduces HP to 0 or below, False otherwise.
        """
        actual_damage = max(0, damage)  # Prevent healing from negative damage
        self.hp -= actual_damage
        return self.hp <= 0

    def gain_xp(self, amount: int) -> None:
        """Adds experience points and checks for level up.

        Args:
            amount: The amount of XP to gain.
        """
        self.xp += amount
        print(f"{self.name} gains {amount} XP.")
        while self.xp >= self.xp_to_next_level:
            self.level_up()

    def level_up(self) -> None:
        """Handles the character leveling up.

        Increases level, resets XP, increases XP threshold, increases stats randomly,
        and increases HP. Prints level up message and new stats.
        """
        self.xp -= self.xp_to_next_level  # Subtract threshold
        self.level += 1
        self.xp_to_next_level = (
            self.level * 100 + (self.level - 1) * 50
        )  # Slightly increasing requirement

        # Stat increases
        self.strength += random.randint(0, 1)  # Smaller increases per level
        self.dexterity += random.randint(0, 1)
        self.constitution += random.randint(0, 1)

        # HP increase
        hp_gain = max(
            1, random.randint(1, 8) + (self.constitution - 10) // 2
        )  # Ensure at least 1 HP gain
        self.hp += hp_gain

        # Recalculate AC based on potential DEX increase
        self.ac = 10 + (self.dexterity - 10) // 2 + self.armor.get("ac_bonus", 0)

        print(
            f"{self.name} has reached level {self.level}! (XP: {self.xp}/{self.xp_to_next_level})"
        )
        print(
            f"  New stats => HP: {self.hp}, AC: {self.ac}, STR: {self.strength}, DEX: {self.dexterity}, CON: {self.constitution}"
        )
        # Reset HP to full on level up? Or maybe just add the gain?
        # For now, just add the gain to current HP.

    def __str__(self) -> str:
        """Returns a string representation of the character's stats."""
        status_str = ", ".join([f"{e['name']}({e['duration']})" for e in self.status_effects])
        status_part = f", Status: [{status_str}]" if status_str else ""
        inventory_str = ", ".join([i.get("name", "?") for i in self.inventory])
        inventory_part = f", Inv: [{inventory_str}]" if inventory_str else ""

        return (
            f"{self.name} ({self.class_name.value} L{self.level}) - HP: {self.hp}, AC: {self.ac}\
"
            f"  Weapon: {self.weapon.get('name', 'None')}, Armor: {self.armor.get('name', 'None')}\
"
            f"  Stats: STR {self.strength}, DEX {self.dexterity}, CON {self.constitution}{status_part}{inventory_part}"
        )
