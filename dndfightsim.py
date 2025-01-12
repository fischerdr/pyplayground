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


class BattleGrid:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.grid = [[' ' for _ in range(width)] for _ in range(height)]
        self.characters = {}
        self.cover = set()
        self.hazards = set()

    def place_character(self, character, x, y):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.characters[character] = (x, y)
            self.grid[y][x] = character.name[0]
        else:
            raise ValueError("Invalid position")

    def move_character(self, character, dx, dy):
        x, y = self.characters[character]
        new_x, new_y = x + dx, y + dy
        if 0 <= new_x < self.width and 0 <= new_y < self.height:
            self.grid[y][x] = ' '
            self.characters[character] = (new_x, new_y)
            self.grid[new_y][new_x] = character.name[0]
            return True
        return False

    def add_cover(self, x, y):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cover.add((x, y))
            self.grid[y][x] = 'C'

    def add_hazard(self, x, y, damage):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.hazards.add((x, y, damage))
            self.grid[y][x] = 'H'

    def is_in_cover(self, character):
        x, y = self.characters[character]
        return any((abs(x-cx) + abs(y-cy) == 1) for cx, cy in self.cover)

    def apply_hazards(self, character):
        x, y = self.characters[character]
        for hx, hy, damage in self.hazards:
            if x == hx and y == hy:
                character.take_damage(damage)
                print(f"{character.name} takes {damage} damage from a hazard!")

    def __str__(self):
        return '\n'.join([''.join(row) for row in self.grid])

class CombatAI:
    def __init__(self, character, personality):
        self.character = character
        self.personality = personality

    def choose_action(self, opponent, battle_grid):
        actions = ['attack', 'move', 'dodge', 'parry', 'use_item']
        weights = self.calculate_action_weights(opponent, battle_grid)
        return random.choices(actions, weights=weights)[0]

    def calculate_action_weights(self, opponent, battle_grid):
        weights = [1, 1, 1, 1, 1]  # Base weights for [attack, move, dodge, parry, use_item]

        # Adjust weights based on personality
        if self.personality == 'aggressive':
            weights[0] *= 2  # More likely to attack
        elif self.personality == 'cautious':
            weights[2] *= 1.5  # More likely to dodge
            weights[3] *= 1.5  # More likely to parry
        elif self.personality == 'tactical':
            weights[1] *= 1.5  # More likely to move
            weights[4] *= 1.5  # More likely to use items

        # Adjust weights based on situation
        char_x, char_y = battle_grid.characters[self.character]
        opp_x, opp_y = battle_grid.characters[opponent]
        distance = abs(char_x - opp_x) + abs(char_y - opp_y)

        if distance > 1:
            weights[1] *= 2  # More likely to move if not adjacent to opponent
        if self.character.hp < self.character.constitution:
            weights[4] *= 2  # More likely to use items when low on health
        if battle_grid.is_in_cover(self.character):
            weights[0] *= 1.5  # More likely to attack if in cover
        if isinstance(self.character, Ranger) and distance > 1:
            weights[0] *= 2  # Rangers more likely to attack at range

        return weights

    def choose_move_direction(self, battle_grid, opponent):
        char_x, char_y = battle_grid.characters[self.character]
        opp_x, opp_y = battle_grid.characters[opponent]
        
        if self.personality == 'aggressive':
            # Move towards opponent
            dx = 1 if opp_x > char_x else -1 if opp_x < char_x else 0
            dy = 1 if opp_y > char_y else -1 if opp_y < char_y else 0
        elif self.personality == 'cautious':
            # Move away from opponent
            dx = -1 if opp_x > char_x else 1 if opp_x < char_x else 0
            dy = -1 if opp_y > char_y else 1 if opp_y < char_y else 0
        else:
            # Move towards cover or randomly
            cover_positions = list(battle_grid.cover)
            if cover_positions:
                target_x, target_y = min(cover_positions, key=lambda pos: (pos[0]-char_x)**2 + (pos[1]-char_y)**2)
                dx = 1 if target_x > char_x else -1 if target_x < char_x else 0
                dy = 1 if target_y > char_y else -1 if target_y < char_y else 0
            else:
                dx, dy = random.choice([(0, 1), (0, -1), (1, 0), (-1, 0)])
        
        return dx, dy

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
        self.personality = random.choice(['aggressive', 'cautious', 'tactical'])
        self.ai = CombatAI(self, self.personality)

    def ranged_attack(self, target, battle_grid):
        base_roll = random.randint(1, 20) + (self.dexterity - 10) // 2
        if battle_grid.is_in_cover(target):
            base_roll -= 2  # Apply cover penalty
        return base_roll

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

def fight(character1, character2, battle_grid):
    print(f"Battle begins between {character1.name} and {character2.name}!")
    print(f"{character1.name} is {character1.personality}")
    print(f"{character2.name} is {character2.personality}")
    print(battle_grid)
    print()

    characters = [character1, character2]
    random.shuffle(characters)  # Randomize initial turn order

    while character1.hp > 0 and character2.hp > 0:
        for character in characters:
            opponent = character2 if character == character1 else character1

            if not character.process_status_effects():
                continue

            battle_grid.apply_hazards(character)
            
            print(f"{character.name}'s turn:")
            action = character.ai.choose_action(opponent, battle_grid)
            
            if action == 'attack':
                if isinstance(character, Ranger):
                    attack_roll = character.ranged_attack(opponent, battle_grid)
                    print(f"{character.name} makes a ranged attack!")
                else:
                    attack_roll = character.attack()
                    print(f"{character.name} attacks!")
                
                if attack_roll == float('inf') or attack_roll >= opponent.ac:
                    damage = character.deal_damage()
                    print(f"{character.name} hits {opponent.name} for {damage} damage.")
                    if opponent.take_damage(damage):
                        print(f"{opponent.name} has been defeated!")
                        return character.name
                    if random.random() < 0.1:  # 10% chance to apply a status effect
                        effect = random.choice([
                            {'name': 'poisoned', 'duration': 3},
                            {'name': 'stunned', 'duration': 1}
                        ])
                        opponent.apply_status_effect(effect)
                else:
                    print(f"{character.name} misses {opponent.name}.")
            
            elif action == 'move':
                dx, dy = character.ai.choose_move_direction(battle_grid, opponent)
                if battle_grid.move_character(character, dx, dy):
                    print(f"{character.name} moves.")
                    print(battle_grid)
                else:
                    print(f"{character.name} couldn't move.")
            
            elif action == 'dodge':
                dodge_bonus = character.dodge()
                print(f"{character.name} dodges, gaining +{dodge_bonus} to AC until next turn.")
            
            elif action == 'parry':
                parry_bonus = character.parry()
                print(f"{character.name} prepares to parry, gaining +{parry_bonus} to AC against next attack.")
            
            elif action == 'use_item':
                item = character.use_item()
                if item:
                    if item['type'] == 'healing':
                        heal_amount = random.randint(item['heal'][0], item['heal'][1])
                        character.hp += heal_amount
                        print(f"{character.name} uses {item['name']} and heals for {heal_amount} HP.")
                    elif item['type'] == 'damage':
                        damage = random.randint(item['damage'][0], item['damage'][1])
                        print(f"{character.name} uses {item['name']} on {opponent.name} for {damage} damage.")
                        if opponent.take_damage(damage):
                            print(f"{opponent.name} has been defeated!")
                            return character.name
                else:
                    print(f"{character.name} has no items to use.")

            # Class-specific actions
            if isinstance(character, Mage) and random.random() < 0.3:  # 30% chance for Mage to cast a spell
                spell_type = random.choice(['offensive', 'defensive'])
                if spell_type == 'offensive':
                    spell_name, damage = character.cast_offensive_spell()
                    if spell_name:
                        print(f"{character.name} casts {spell_name}!")
                        if opponent.take_damage(damage):
                            print(f"{opponent.name} has been defeated!")
                            return character.name
                else:
                    heal_amount = character.cast_defensive_spell()
                    if heal_amount > 0:
                        print(f"{character.name} heals for {heal_amount} HP.")

            character.end_turn()
            print(f"{character.name}: HP {character.hp}, AC {character.ac}")
            print(f"{opponent.name}: HP {opponent.hp}, AC {opponent.ac}")
            print()

            # Check if the battle is over after each action
            if character1.hp <= 0:
                return character2.name
            elif character2.hp <= 0:
                return character1.name

    return "Draw"


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
# Example usage
battle_grid = BattleGrid(5, 5)
character1 = create_random_character("Gandalf", "Mage")
character2 = create_random_character("Aragorn", "Warrior")

battle_grid.place_character(character1, 0, 0)
battle_grid.place_character(character2, 4, 4)
battle_grid.add_cover(2, 2)
battle_grid.add_hazard(1, 1, 5)

winner = fight(character1, character2, battle_grid)
print(f"\nThe winner is {winner}!")