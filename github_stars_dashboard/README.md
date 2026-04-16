# GitHub Stars Dashboard

A comprehensive dashboard for tracking and analyzing GitHub repository stars.

## Overview

This project provides:
- Real-time tracking of GitHub repository stars
- Automatic categorization of repositories
- Activity logging and analytics
- RESTful API for data access
- CLI tools for management

## Features

- **Repository Tracking**: Monitor stars, forks, and repository metadata
- **Automatic Categorization**: Categorize repositories based on patterns
- **Activity Logging**: Track all changes and operations
- **FastAPI Backend**: Modern, async API server
- **SQLite Database**: Lightweight, file-based storage
- **CLI Tools**: Command-line interface for management

## Getting Started

### Prerequisites

- Python 3.12+
- pip or poetry

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd github-stars-dashboard

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Set up environment variables
cp .env.example .env
# Edit .env and add your GITHUB_TOKEN

# Run pre-commit hooks
pre-commit install

# Run tests
pytest

# Start the application
python -m github_stars.cli
```

## Configuration

Set up your environment variables in `.env`:

```bash
GITHUB_TOKEN=your_github_token
DATABASE_URL=sqlite:///./github_stars.db
LOG_LEVEL=INFO
```

## Project Structure

```
github-stars-dashboard/
├── src/github_stars/    # Main application code
│   ├── __init__.py
│   ├── main.py          # FastAPI application
│   ├── models.py        # Database models
│   ├── database.py      # Database configuration
│   ├── config_loader.py # Configuration management
│   └── utils/           # Utility functions
├── tests/               # Test suite
├── scripts/             # Helper scripts
├── config/              # Configuration files
├── docker/              # Docker configuration
└── docs/                # Documentation
```

## API Endpoints

- `GET /repositories` - List all tracked repositories
- `GET /repositories/{id}` - Get repository details
- `POST /repositories` - Add new repository
- `GET /stars` - Get star history
- `GET /categories` - List categories
- `POST /categories` - Create category

## Development

### Running Tests

```bash
pytest -v
pytest --cov=github_stars
```

### Code Quality

```bash
black src/github_stars/
isort src/github_stars/
ruff check src/github_stars/
mypy src/github_stars/
```

### Pre-commit Hooks

Pre-commit hooks run automatically on commit:
- Black (code formatting)
- isort (import sorting)
- ruff (linting)
- mypy (type checking)

## License

MIT License
