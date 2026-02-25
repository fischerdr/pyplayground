"""Handles the rich-based terminal display for the simulation."""

from typing import TYPE_CHECKING, List

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from .characters.base import Character
    from .environment import BattleGrid


console = Console()


def create_layout() -> Layout:
    """Defines the main layout structure (Map/C1, Log/C2, Status)."""
    # Create the main wrapper to constrain height
    main_wrapper = Layout(name="root")
    main_wrapper.split_column(
        Layout(name="app", ratio=1),  # Create the app area first
        Layout(Panel(" ", style="dim"), name="spacer", ratio=1),  # Optional spacer
    )

    # Get a reference to the app layout area
    app_layout_ref = main_wrapper["app"]

    # Split the app layout into Top Row, Middle Row, Status Bar
    app_layout_ref.split_column(
        Layout(name="top_row", ratio=3),
        Layout(name="middle_row", ratio=3),
        Layout(name="status_pane", size=1),
    )

    # Split Top Row: Map (Left) and Combatant 1 (Right)
    app_layout_ref["top_row"].split_row(
        Layout(name="map_pane", ratio=3),
        Layout(name="combatant1_pane", ratio=1),
    )

    # Split Middle Row: Log (Left) and Combatant 2 (Right)
    app_layout_ref["middle_row"].split_row(
        Layout(name="log_pane", ratio=3),
        Layout(name="combatant2_pane", ratio=1),
    )

    # Assign default content placeholders within the app layout reference
    app_layout_ref["top_row"]["map_pane"].update(Panel("[Map Placeholder]", title="Battle Map"))
    app_layout_ref["top_row"]["combatant1_pane"].update(Panel("[Combatant 1 Info]", title="Combatant 1"))
    app_layout_ref["middle_row"]["log_pane"].update(Panel("[Combat Log]", title="Log"))
    app_layout_ref["middle_row"]["combatant2_pane"].update(Panel("[Combatant 2 Info]", title="Combatant 2"))
    app_layout_ref["status_pane"].update(Text("Status: Initializing...", justify="center"))

    return main_wrapper  # Return the wrapper


def generate_map_renderable(grid: "BattleGrid") -> Panel:
    """Generates the renderable content for the map pane."""
    # Use the new render_rich method for map content
    map_content = grid.render_rich()
    return Panel(map_content, title="Battle Map")


def generate_combatant_renderable(character: "Character") -> Panel:
    """Generates the renderable content for a combatant pane."""
    # Add Weapon, Armor, and Status Effects
    weapon_name = character.weapon.get("name", "None")
    armor_name = character.armor.get("name", "None")
    status_str = ""
    if character.status_effects:
        status_str = ", ".join([f"{e['name']}({e['duration']})" for e in character.status_effects])
        status_str = f"\nStatus: {status_str}"

    # Expanded info including core stats, level, and XP
    info = (
        f"Name: {character.name} ({character.class_name.value} L{character.level})\n"
        f"HP: {character.hp}/{character.max_hp} | AC: {character.ac}\n"
        f"STR: {character.strength} | DEX: {character.dexterity} | CON: {character.constitution}\n"
        f"XP: {character.xp}/{character.xp_to_next_level}\n"
        f"Weapon: {weapon_name}\nArmor: {armor_name}"
        f"{status_str}"
    )
    return Panel(info, title=character.name)


def generate_log_renderable(log_messages: List[str], max_lines: int = 10) -> Panel:
    """Generates the renderable content for the combat log pane."""
    # Display the last 'max_lines' messages
    start_index = max(0, len(log_messages) - max_lines)
    displayed_messages = log_messages[start_index:]
    log_content = "\n".join(displayed_messages)
    # Use Text object for potential future styling within the log
    return Panel(Text(log_content), title="Combat Log")


def update_layout(
    layout: Layout,
    grid: "BattleGrid",
    combatant1: "Character",
    combatant2: "Character",
    log_messages: List[str],
    status: str = "Running...",
):
    """Updates the layout with the current game state."""
    # Update panes using the new layout structure
    layout["app"]["top_row"]["map_pane"].update(generate_map_renderable(grid))
    layout["app"]["top_row"]["combatant1_pane"].update(generate_combatant_renderable(combatant1))

    other_chars = [c for c in grid.get_characters() if c != combatant1]
    if other_chars:
        layout["app"]["middle_row"]["combatant2_pane"].update(generate_combatant_renderable(other_chars[0]))
    else:  # Only one character left?
        layout["app"]["middle_row"]["combatant2_pane"].update(Panel("--- Empty ---", title="Combatant 2"))  # Improved placeholder

    layout["app"]["middle_row"]["log_pane"].update(generate_log_renderable(log_messages))
    layout["app"]["status_pane"].update(Text(f"Status: {status}", justify="center"))
