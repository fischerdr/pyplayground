"""Main entry point for the DnD Fight Simulator."""

# Note: If running this script directly from the 'src' directory,
# Python might have trouble finding the 'dndfightsim' package.
# It's better to run this from the project root directory using:
# python -m src.dndfightsim
# Or, install the package (e.g., using pip install -e .) and run dndfightsim.

# Attempt relative import assuming execution context allows it
try:
    from .dndfightsim.simulation import run_example_grid_fight, run_leveling_simulation
except ImportError:
    # Fallback for running script directly (less ideal)
    print(
        "Import Warning: Attempting fallback import. Run using 'python -m src.dndfightsim' for reliability."
    )
    try:
        from dndfightsim.simulation import run_example_grid_fight, run_leveling_simulation
    except ImportError as e:
        print(f"Fatal Error: Could not import simulation components. {e}")
        print("Please ensure you are running from the project root or have the package installed.")
        exit(1)


def main():
    """Runs the main simulation modes."""
    print("Starting DnD Fight Simulator...")
    run_leveling_simulation()
    run_example_grid_fight()
    print("\nSimulation Complete.")


if __name__ == "__main__":
    main()
