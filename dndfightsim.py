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
        """
        Initializes a new Character.

        :param name: The name of the character.

        The character's strength, dexterity, and constitution are randomly
        generated. The character is given a random weapon and armor, and its
        hit points and armor class are calculated accordingly. The character
        starts at level 1 with 0 experience points and a requirement of 100
        experience points to reach the next level.
        """
        self.name = name
        self.strength = random.randint(8, 18)
        self.dexterity = random.randint(8, 18)
        self.constitution = random.randint(8, 18)
        self.hp = self.constitution * 2
        self.weapon = random.choice(weapons)
        self.armor = random.choice(armors)
        self.ac = 10 + (self.dexterity - 10) // 2 + self.armor["ac_bonus"]
        self.level = 1
        self.xp = 0
        self.xp_to_next_level = 100
        self.status_effects = []
        self.inventory = []

    def attack(self):
        roll = random.randint(1, 20)
        if roll == 20:
            print(f"Critical hit by {self.name}!")
            return float('inf')  # Guarantee a hit
        elif roll == 1:
            print(f"Critical miss by {self.name}!")
            return float('-inf')  # Guarantee a miss
        return roll + (self.strength - 10) // 2

    def deal_damage(self):
        base_damage = random.randint(self.weapon["damage"][0], self.weapon["damage"][1])
        damage = base_damage + (self.strength - 10) // 2
        if self.attack() == float('inf'):  # Critical hit
            damage *= 2
        return damage

    def dodge(self):
        self.ac += 2  # Temporary AC boost
        print(f"{self.name} takes a defensive stance. AC increased by 2 for this turn.")

    def parry(self):
        parry_bonus = (self.dexterity - 10) // 2
        print(f"{self.name} prepares to parry. Next attack against them has a -{parry_bonus} penalty.")
        return parry_bonus

    def use_item(self):
        if self.inventory:
            item = random.choice(self.inventory)
            if item["type"] == "healing":
                heal_amount = random.randint(item["heal"][0], item["heal"][1])
                self.hp += heal_amount
                print(f"{self.name} uses {item['name']} and heals for {heal_amount} HP.")
            elif item["type"] == "damage":
                return item
            self.inventory.remove(item)
        else:
            print(f"{self.name} has no items to use.")
            return None

    def apply_status_effect(self, effect):
        self.status_effects.append(effect)
        print(f"{self.name} is now {effect['name']}.")

    def process_status_effects(self):
        for effect in self.status_effects:
            if effect['name'] == 'poisoned':
                damage = random.randint(1, 4)
                self.hp -= damage
                print(f"{self.name} takes {damage} poison damage.")
            elif effect['name'] == 'stunned':
                print(f"{self.name} is stunned and loses their turn.")
                return False
            effect['duration'] -= 1
        self.status_effects = [effect for effect in self.status_effects if effect['duration'] > 0]
        return True

    def end_turn(self):
        self.ac = 10 + (self.dexterity - 10) // 2 + self.armor["ac_bonus"]  # Reset AC
  
    def take_damage(self, damage):
        self.hp -= damage
        return self.hp <= 0

    def gain_xp(self, amount):
        self.xp += amount
        if self.xp >= self.xp_to_next_level:
            self.level_up()

    def level_up(self):
        self.level += 1
        self.xp -= self.xp_to_next_level
        self.xp_to_next_level = self.level * 100

        self.strength += random.randint(0, 2)
        self.dexterity += random.randint(0, 2)
        self.constitution += random.randint(0, 2)
        self.hp += random.randint(1, 8) + (self.constitution - 10) // 2

        print(f"{self.name} has reached level {self.level}!")
        print(f"New stats: STR: {self.strength}, DEX: {self.dexterity}, CON: {self.constitution}, HP: {self.hp}")

    def __str__(self):
        return (f"{self.name} (Level {self.level}) - HP: {self.hp}, AC: {self.ac}, "
                f"Weapon: {self.weapon['name']}, Armor: {self.armor['name']}, "
                f"STR: {self.strength}, DEX: {self.dexterity}, CON: {self.constitution}")

class Warrior(Character):
    def __init__(self, name):
        super().__init__(name)
        self.class_name = "Warrior"

class Mage(Character):
    def __init__(self, name):
        super().__init__(name)
        self.class_name = "Mage"
        self.spell_slots = 3
        self.active_defense_spell = None
        self.defense_spell_duration = 0

    def cast_offensive_spell(self):
        if self.spell_slots > 0:
            spell = random.choice(offensive_spells)
            self.spell_slots -= 1
            damage = random.randint(spell["damage"][0], spell["damage"][1])
            return spell["name"], damage
        return None, 0

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
        return 0

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
        return random.randint(1, 20) + (self.dexterity - 10) // 2

    def ranged_damage(self):
        base_damage = random.randint(self.weapon["damage"][0], self.weapon["damage"][1])
        return base_damage + (self.dexterity - 10) // 2

class Rogue(Character):
    def __init__(self, name):
        super().__init__(name)
        self.class_name = "Rogue"
        self.sneak_attack_damage = 2

    def sneak_attack(self):
        return random.randint(1, 6) * self.sneak_attack_damage

    def attack(self):
        base_roll = super().attack()
        if random.random() < 0.2:  # 20% chance of sneak attack
            print(f"{self.name} performs a sneak attack!")
            return base_roll + self.sneak_attack()
        return base_roll

def create_random_character(name, character_class):
    character = Character(name)
    if character_class == "Warrior":
        character = Warrior(name)
    elif character_class == "Mage":
        character = Mage(name)
    elif character_class == "Ranger":
        character = Ranger(name)
    elif character_class == "Rogue":
        character = Rogue(name)

    # Add some random items to the inventory
    items = [
        {"name": "Health Potion", "type": "healing", "heal": (5, 10)},
        {"name": "Fire Bomb", "type": "damage", "damage": (3, 8)},
        {"name": "Antidote", "type": "healing", "heal": (1, 4)}
    ]
    character.inventory = random.sample(items, 2)

    return character

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
                            character.gain_xp(opponent.level * 50)
                            return character.name
                        character.gain_xp(damage)
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
                        character.gain_xp(opponent.level * 50)
                        return character.name
                    character.gain_xp(damage)
                else:
                    print(f"{character.name} misses {opponent.name}.")
            # End turn adjustments
            if isinstance(character, Mage):
                character.end_turn()

# Create characters and simulate multiple fights
# Creating characters with specific classes
character1 = create_random_character("Gandalf", "Mage")
character2 = create_random_character("Aragorn", "Warrior")
character3 = create_random_character("Legolas", "Ranger")
character4 = create_random_character("Bilbo", "Rogue")

# Simulate multiple fights to showcase leveling
for i in range(5):
    print(f"\nBattle {i+1}:")
    fighters = [character1, character2, character3, character4]
    random.shuffle(fighters)
    winner = fight(fighters[0], fighters[1])
    print(f"\nThe winner is {winner}!")

# Print final character stats
for character in [character1, character2, character3, character4]:
    print("\n" + str(character))
# Fight!
winner = fight(character1, character2)
print(f"\nThe winner is {winner}!")
