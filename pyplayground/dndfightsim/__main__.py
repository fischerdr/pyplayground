# src/dndfightsim/__main__.py
"""Allows the package to be run as a script using python -m src.dndfightsim."""

import sys

try:
    from .simulation import run_example_grid_fight, run_leveling_simulation
except ImportError as e:
    print(f"Error importing simulation components within package __main__.py: {e}")
    print("This might happen if the package structure is incorrect or dependencies are missing.")
    # Attempt to give a more helpful message if run from the wrong directory
    if "attempted relative import with no known parent package" in str(e):
        print(
            "Hint: Try running this from the project root directory using 'python -m src.dndfightsim'"
        )
    sys.exit(1)


def main_package_entry():
    """Runs the main simulation modes."""
    print("Starting DnD Fight Simulator (via package entry)...")
    run_leveling_simulation()
    run_example_grid_fight()
    print("\nSimulation Complete.")


# This ensures the main function runs only when the module is executed directly
if __name__ == "__main__":
    main_package_entry()
