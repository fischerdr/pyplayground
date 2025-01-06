import random

# Lists of possible weapons and armors
weapons = [
    {"name": "Short Sword", "damage": (1, 6)},
    {"name": "Long Sword", "damage": (1, 8)},
    {"name": "Bow", "damage": (1, 8)},
    {"name": "Dagger", "damage": (1, 4)}
]

armors = [
    {"name": "Leather Armor", "ac_bonus": 1},
    {"name": "Chain Mail", "ac_bonus": 3},
    {"name": "Plate Armor", "ac_bonus": 5},
    {"name": "Cloth", "ac_bonus": 0}
]

# Offensive and defensive spells for Mage
offensive_spells = [
    {"name": "Fireball", "damage": (5, 10)},
    {"name": "Lightning Bolt", "damage": (4, 8)}
]

defensive_spells = [
    {"name": "Shield", "ac_bonus": 2, "duration": 3},  # Lasts for 3 turns
    {"name": "Healing Light", "heal": (3, 6)}
]

class Character:
    def __init__(self, name):
        self.name = name
        self.strength = random.randint(1, 20)
        self.dexterity = random.randint(1, 20)
        self.constitution = random.randint(1, 20)
        self.hp = self.constitution * 2  # Hit points based on Constitution
        self.weapon = random.choice(weapons)
        self.armor = random.choice(armors)
        self.ac = 10 + (self.dexterity - 10) // 2 + self.armor["ac_bonus"]
    
    def attack(self):
        return random.randint(1, 20) + (self.strength - 10) // 2  # Melee attack roll

    def deal_damage(self):
        base_damage = random.randint(self.weapon["damage"][0], self.weapon["damage"][1])
        return base_damage + (self.strength - 10) // 2  # Melee damage roll

    def take_damage(self, damage):
        self.hp -= damage
        return self.hp <= 0  # Returns True if character is dead

    def __str__(self):
        return (f"{self.name} - HP: {self.hp}, AC: {self.ac}, Weapon: {self.weapon['name']}, "
                f"Armor: {self.armor['name']}, STR: {self.strength}, DEX: {self.dexterity}, "
                f"CON: {self.constitution}")

class Warrior(Character):
    def __init__(self, name):
        super().__init__(name)
        self.class_name = "Warrior"

class Mage(Character):
    def __init__(self, name):
        super().__init__(name)
        self.class_name = "Mage"
        self.spell_slots = 3  # Limited number of spells
        self.active_defense_spell = None
        self.defense_spell_duration = 0

    def cast_offensive_spell(self):
        if self.spell_slots > 0:
            spell = random.choice(offensive_spells)
            self.spell_slots -= 1
            return spell["name"], random.randint(spell["damage"][0], spell["damage"][1])
        return None, 0  # No spells left

    def cast_defensive_spell(self):
        if self.spell_slots > 0:
            spell = random.choice(defensive_spells)
            self.spell_slots -= 1
            if "ac_bonus" in spell:
                self.active_defense_spell = spell
                self.defense_spell_duration = spell["duration"]
                self.ac += spell["ac_bonus"]
            elif "heal" in spell:
                heal_amount = random.randint(spell["heal"][0], spell["heal"][1])
                self.hp += heal_amount
                print(f"{self.name} casts {spell['name']} and heals {heal_amount} HP!")
                return heal_amount
        return 0  # No healing if no spell slots or spell wasn't healing

    def end_turn(self):
        if self.active_defense_spell:
            self.defense_spell_duration -= 1
            if self.defense_spell_duration <= 0:
                self.ac -= self.active_defense_spell["ac_bonus"]
                self.active_defense_spell = None

class Ranger(Character):
    def __init__(self, name):
        super().__init__(name)
        self.class_name = "Ranger"

    def ranged_attack(self):
        return random.randint(1, 20) + (self.dexterity - 10) // 2  # Dexterity-based attack roll

    def ranged_damage(self):
        base_damage = random.randint(self.weapon["damage"][0], self.weapon["damage"][1])
        return base_damage + (self.dexterity - 10) // 2

def create_random_character(name, character_class):
    if character_class == "Warrior":
        return Warrior(name)
    elif character_class == "Mage":
        return Mage(name)
    elif character_class == "Ranger":
        return Ranger(name)
    else:
        return Character(name)

def fight(character1, character2):
    print(f"Battle begins between {character1.name} the {character1.class_name} and {character2.name} the {character2.class_name}!\n")
    print(character1)
    print(character2)
    print()

    while character1.hp > 0 and character2.hp > 0:
        for character, opponent in [(character1, character2), (character2, character1)]:
            if isinstance(character, Mage) and character.spell_slots > 0:
                if random.choice([True, False]):  # Randomly decide to cast offensive or defensive
                    spell_name, damage = character.cast_offensive_spell()
                    if damage:
                        print(f"{character.name} casts {spell_name} dealing {damage} damage to {opponent.name}.")
                        if opponent.take_damage(damage):
                            print(f"{opponent.name} has been defeated!")
                            return character.name
                else:
                    character.cast_defensive_spell()
            else:
                # Melee or Ranged Attack
                attack_roll = character.attack() if not isinstance(character, Ranger) else character.ranged_attack()
                if attack_roll >= opponent.ac:
                    damage = character.deal_damage() if not isinstance(character, Ranger) else character.ranged_damage()
                    print(f"{character.name} hits {opponent.name} for {damage} damage.")
                    if opponent.take_damage(damage):
                        print(f"{opponent.name} has been defeated!")
                        return character.name
                else:
                    print(f"{character.name} misses {opponent.name}.")
            # End turn adjustments
            if isinstance(character, Mage):
                character.end_turn()

# Creating two random characters with specific classes
character1 = create_random_character("Gandalf", "Mage")
character2 = create_random_character("Aragorn", "Warrior")

# Fight!
winner = fight(character1, character2)
print(f"\nThe winner is {winner}!")
