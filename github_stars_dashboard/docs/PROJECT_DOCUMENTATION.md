# GitHub Stars Dashboard - Complete Project Documentation

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [Setup Instructions](#setup-instructions)
5. [Usage Guide](#usage-guide)
6. [API Reference](#api-reference)
7. [Live Debug Testing](#live-debug-testing)
8. [Configuration](#configuration)
9. [Troubleshooting](#troubleshooting)

---

## Project Overview

The GitHub Stars Dashboard is a web application for tracking, categorizing, and analyzing GitHub repositories. It provides real-time statistics, automated categorization, and visual analytics for starred repositories.

### Key Features

- **Repository Management**: Add, edit, and delete GitHub repositories
- **Auto-Categorization**: Intelligent pattern-based categorization of repositories
- **Real-time Sync**: Randomized interval synchronization with GitHub API
- **Analytics Dashboard**: Visual statistics and category breakdowns
- **Activity Tracking**: Monitor repository changes and updates
- **Dark Mode**: Theme toggle for comfortable viewing

---

## Architecture

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      Frontend (Flask)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   index.html│  │  styles.css │  │      app.js             │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│         │                │                    │                 │
│         └────────────────┴────────────────────┘                 │
│                              │                                  │
└──────────────────────────────┼──────────────────────────────────┘
                               │ HTTP/REST API
┌──────────────────────────────┼──────────────────────────────────┐
│         Backend (Flask API)   │                                  │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                    app.py                                  │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │ │
│  │  │ /api/stats  │  │ /api/repos  │  │ /api/categories  │  │ │
│  │  └─────────────┘  └─────────────┘  └──────────────────┘  │ │
│  └───────────────────────────────────────────────────────────┘ │
│                              │                                  │
└──────────────────────────────┼──────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────┐
│         Core Modules          │                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  database.py│  │  models.py  │  │    config_loader.py     │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  fetcher.py │  │ categorizer │  │      sync.py            │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ scheduler.py│  │  logger.py  │  │      utils.py           │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└──────────────────────────────┼──────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────┐
│       External Services       │                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   SQLite    │  │ GitHub API  │  │     Environment Vars    │ │
│  │   Database  │  │ (Rate Limit)│  │   (GITHUB_TOKEN, etc.)  │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Module Structure

```
github_stars_dashboard/
├── src/
│   └── github_stars/
│       ├── __init__.py
│       ├── app.py              # Flask application & API routes
│       ├── database.py         # Database engine & session management
│       ├── models.py           # SQLAlchemy models (Repository, Star, Category, ActivityLog)
│       ├── config_loader.py    # Configuration management
│       ├── fetcher.py          # GitHub API client
│       ├── categorizer.py      # Auto-categorization engine
│       ├── sync.py             # Data synchronization logic
│       ├── scheduler.py        # Random interval sync scheduler
│       └── logger.py           # Structured logging
├── github_stars_dashboard/
│   ├── static/
│   │   ├── css/
│   │   │   └── styles.css      # UI styles with dark mode support
│   │   └── js/
│   │       └── app.js          # Frontend application logic
│   └── templates/
│       └── index.html          # Main dashboard template
├── config/
│   └── categories.json         # Category patterns configuration
├── data/
│   └── github_stars.db         # SQLite database (auto-created)
├── docker/
│   ├── Dockerfile              # Container image definition
│   └── entrypoint.sh           # Container startup script
├── docker-compose.yml          # Container orchestration
├── .env                        # Production environment variables
├── .env.dev                    # Development environment variables
├── .env.prod                   # Production environment variables
└── docs/
    ├── progress.md             # Phase-based progress tracking
    └── PROJECT_DOCUMENTATION.md # This file
```

---

## Features

### 1. Repository Management

- **Add Repositories**: Manually add GitHub repositories via web interface
- **Edit Repositories**: Update repository owner/name information
- **Delete Repositories**: Remove repositories from tracking
- **Search & Filter**: Find repositories by name, category, or language
- **Sort Options**: Sort by stars, name, or last updated date

### 2. Auto-Categorization Engine

- **Pattern Matching**: Intelligent regex-based categorization
- **Custom Patterns**: Define custom category patterns in `config/categories.json`
- **Category Statistics**: View repository counts and total stars per category
- **Uncategorized Handling**: Repositories without matching patterns are marked as uncategorized

### 3. Data Synchronization

- **Random Interval Sync**: Uses `random.randint()` for unpredictable sync intervals
- **GitHub API Integration**: Fetches real-time star counts and repository metadata
- **Activity Logging**: Tracks all sync operations and changes
- **Rate Limit Handling**: Respects GitHub API rate limits

### 4. Analytics Dashboard

- **Real-time Statistics**: Total repositories, stars, and active repos
- **Category Breakdown**: Visual representation of repository distribution
- **Activity Feed**: Recent sync and update events
- **Responsive Design**: Works on desktop and mobile devices

### 5. Dark Mode

- **Theme Toggle**: Click the moon/sun icon in the header to switch themes
- **Persistent Preference**: Theme choice saved to localStorage
- **System Preference Detection**: Auto-detects system dark mode preference
- **Smooth Transitions**: CSS transitions for seamless theme switching

---

## Setup Instructions

### Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- Git (for cloning the repository)

### Local Development Setup

#### 1. Clone the Repository

```bash
cd /development/git/pyplayground/github_stars_dashboard
```

#### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.dev .env
```

Edit `.env` and add your GitHub token:

```env
GITHUB_TOKEN=your_github_token_here
DATABASE_URL=sqlite:///data/github_stars.db
FLASK_ENV=development
```

**Getting a GitHub Token:**
1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate new token (classic)
3. Select scopes: `repo`, `public_repo`
4. Copy the token and paste it in `.env`

#### 5. Initialize Database

```bash
python -c "from src.github_stars.database import init_db; init_db()"
```

#### 6. Run the Application

```bash
python src/github_stars/app.py
```

The application will start at `http://localhost:5000`

### Docker Setup

#### 1. Build the Image

```bash
docker build -t github-stars-dashboard -f docker/Dockerfile .
```

#### 2. Run with Docker Compose

```bash
docker-compose up -d
```

#### 3. Access the Application

```
http://localhost:5000
```

#### 4. View Logs

```bash
docker-compose logs -f
```

### Podman Setup (Recommended)

```bash
podman-compose -f docker-compose.yml up -d
```

---

## Usage Guide

### Getting Started

1. **Access the Dashboard**
   - Open your browser and navigate to `http://localhost:5000`

2. **Add Your First Repository**
   - Click the "Add Repository" button
   - Enter the owner name (e.g., `torvalds`)
   - Enter the repository name (e.g., `linux`)
   - Click "Add Repository"

3. **Sync Data**
   - Click the "Sync Now" button to fetch latest star counts
   - The scheduler automatically syncs at random intervals (30-120 seconds)

4. **Browse Categories**
   - Navigate to the "Categories" tab to see auto-categorized repositories
   - View statistics for each category

5. **Monitor Activity**
   - Check the "Activity" tab to see recent sync operations
   - View timestamps and sync results

### Dark Mode

- **Toggle**: Click the moon icon (🌙) in the header to enable dark mode
- **Switch Back**: Click the sun icon (☀️) to return to light mode
- **Persistence**: Your preference is automatically saved

### Managing Repositories

#### Adding a Repository

```
1. Click "Add Repository" button
2. Fill in owner and repository name
3. Click "Add"
4. Repository will be categorized automatically
```

#### Editing a Repository

```
1. Click the edit icon (✏️) next to the repository
2. Update owner or name in the prompt
3. Confirm the changes
```

#### Deleting a Repository

```
1. Click the delete icon (🗑️) next to the repository
2. Confirm deletion in the dialog
3. Repository is removed from tracking
```

### Filtering and Sorting

#### Filter by Category

```
1. Select a category from the dropdown
2. Table updates to show only matching repositories
```

#### Search Repositories

```
1. Type in the search box
2. Results filter by owner/name match
```

#### Sort Options

```
- Stars: Sort by star count (descending)
- Name: Sort alphabetically
- Updated: Sort by last update date
```

---

## API Reference

### Endpoints

#### Statistics

**GET /api/stats**

Returns dashboard statistics.

**Response:**
```json
{
  "total_repos": 42,
  "total_stars": 1523,
  "active_repos": 38,
  "categories_count": 5,
  "categories": [
    {
      "name": "Linux Kernel",
      "count": 10,
      "total_stars": 850
    }
  ]
}
```

#### Repositories

**GET /api/repositories**

Returns all tracked repositories.

**Response:**
```json
[
  {
    "id": 1,
    "owner": "torvalds",
    "name": "linux",
    "stars": 72000,
    "language": "C",
    "category": "Linux Kernel",
    "active": true,
    "updated_at": "2026-04-17T10:30:00Z"
  }
]
```

**POST /api/repositories**

Add a new repository.

**Request:**
```json
{
  "owner": "torvalds",
  "name": "linux"
}
```

**DELETE /api/repositories/{id}**

Delete a repository by ID.

**PUT /api/repositories/{id}**

Update repository information.

**Request:**
```json
{
  "owner": "new_owner",
  "name": "new_name",
  "category": "Linux Kernel"
}
```

#### Categories

**GET /api/categories**

Returns all categories with statistics.

**Response:**
```json
[
  {
    "id": 1,
    "name": "Linux Kernel",
    "pattern": "^linux$",
    "repo_count": 10,
    "total_stars": 850
  }
]
```

#### Activity

**GET /api/activity/recent**

Returns recent activity logs.

**Response:**
```json
[
  {
    "id": 1,
    "type": "sync",
    "message": "Synced 5 repositories",
    "timestamp": "2026-04-17T11:00:00Z"
  }
]
```

#### Sync

**POST /api/sync**

Trigger manual synchronization.

**Response:**
```json
{
  "status": "success",
  "synced": 5,
  "message": "Synchronization completed"
}
```

---

## Live Debug Testing

### Testing Checklist

#### 1. Frontend Functionality

**Test Dark Mode:**
```bash
# 1. Open http://localhost:5000
# 2. Click the moon icon (🌙)
# 3. Verify:
#    - Background changes to dark (#1a1a2e)
#    - Text becomes light (#eaeaea)
#    - Icon changes to sun (☀️)
# 4. Refresh page - dark mode persists
# 5. Click sun icon - returns to light mode
```

**Test Repository Management:**
```bash
# 1. Click "Add Repository"
# 2. Enter owner: "torvalds", name: "linux"
# 3. Verify repository appears in table
# 4. Click edit icon - update name
# 5. Verify changes saved
# 6. Click delete icon - confirm deletion
# 7. Verify repository removed
```

**Test Filtering:**
```bash
# 1. Add multiple repositories with different categories
# 2. Select category filter
# 3. Verify only matching repos shown
# 4. Type in search box
# 5. Verify real-time filtering
# 6. Change sort option
# 7. Verify table reorders correctly
```

#### 2. Backend Functionality

**Test API Endpoints:**
```bash
# Test statistics endpoint
curl http://localhost:5000/api/stats

# Test repositories endpoint
curl http://localhost:5000/api/repositories

# Test categories endpoint
curl http://localhost:5000/api/categories

# Test activity endpoint
curl http://localhost:5000/api/activity/recent

# Test sync endpoint
curl -X POST http://localhost:5000/api/sync
```

**Test Database Operations:**
```bash
# Check database exists
ls -la data/github_stars.db

# Query database
sqlite3 data/github_stars.db "SELECT * FROM repositories LIMIT 5;"

# Check activity logs
sqlite3 data/github_stars.db "SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT 5;"
```

#### 3. Synchronization Testing

**Test Random Interval Sync:**
```bash
# 1. Monitor logs during sync
tail -f data/app.log

# 2. Verify sync occurs at random intervals (30-120 seconds)
# 3. Check activity feed for sync messages
# 4. Verify star counts update correctly
```

**Test Manual Sync:**
```bash
# 1. Click "Sync Now" button
# 2. Verify loading indicator appears
# 3. Wait for sync completion
# 4. Check notification message
# 5. Verify data updated
```

#### 4. GitHub API Integration

**Test Rate Limit Handling:**
```bash
# 1. Check GitHub API rate limit in response headers
curl -I http://localhost:5000/api/stats

# 2. Monitor for rate limit errors
grep "rate limit" data/app.log

# 3. Verify graceful degradation on rate limit
```

#### 5. Dark Mode Testing

**CSS Verification:**
```bash
# Check CSS variables defined
grep -A 10 ":root" static/css/styles.css

# Check dark mode overrides
grep -A 10 "body.dark-mode" static/css/styles.css

# Verify all elements have dark mode styles
grep "dark-mode" static/css/styles.css
```

**JavaScript Verification:**
```bash
# Check theme toggle function
grep -A 20 "function initDarkMode" static/js/app.js

# Verify localStorage persistence
grep "localStorage" static/js/app.js
```

#### 6. Logging Verification

**Check Log Levels:**
```bash
# View INFO level logs
grep "INFO" data/app.log | head -20

# View DEBUG level logs
grep "DEBUG" data/app.log | head -20

# View ERROR level logs
grep "ERROR" data/app.log
```

**Verify Structured Logging:**
```bash
# Check JSON format in logs
cat data/app.log | grep -o '{"timestamp":.*}' | head -5
```

### Debug Commands

**Check Application Status:**
```bash
# Check if Flask is running
ps aux | grep "app.py"

# Check port binding
netstat -tlnp | grep 5000
```

**View Logs:**
```bash
# Flask logs
tail -f data/app.log

# Error logs
grep "ERROR" data/app.log

# Sync logs
grep "sync" data/app.log
```

**Database Inspection:**
```bash
# Open database shell
sqlite3 data/github_stars.db

# List tables
.tables

# Check repository count
SELECT COUNT(*) FROM repositories;

# Check recent activity
SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT 10;
```

**API Testing with curl:**
```bash
# Test all endpoints
curl http://localhost:5000/api/stats
curl http://localhost:5000/api/repositories
curl http://localhost/5000/api/categories
curl http://localhost/5000/api/activity/recent

# Add repository
curl -X POST http://localhost:5000/api/repositories \
  -H "Content-Type: application/json" \
  -d '{"owner": "torvalds", "name": "linux"}'

# Trigger sync
curl -X POST http://localhost:5000/api/sync
```

### Common Issues and Solutions

#### Issue: Dark mode not persisting
**Solution:** Check localStorage in browser console:
```javascript
console.log(localStorage.getItem('dashboard-theme'))
```

#### Issue: Sync not occurring
**Solution:** Check scheduler logs:
```bash
grep "scheduler" data/app.log
```

#### Issue: GitHub API rate limit
**Solution:** Wait for rate limit reset or add more tokens:
```bash
grep "rate limit" data/app.log
```

#### Issue: Database connection error
**Solution:** Check database file permissions:
```bash
ls -la data/github_stars.db
chmod 644 data/github_stars.db
```

---

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `GITHUB_TOKEN` | GitHub API token | None | Yes |
| `DATABASE_URL` | Database connection string | `sqlite:///data/github_stars.db` | No |
| `FLASK_ENV` | Flask environment | `production` | No |
| `PORT` | Server port | `5000` | No |

### Category Patterns

Edit `config/categories.json` to customize categorization:

```json
{
  "categories": [
    {
      "name": "Linux Kernel",
      "pattern": "^linux$",
      "description": "Linux kernel and related projects"
    },
    {
      "name": "Python Frameworks",
      "pattern": "^(django|flask|fastapi|bottle)$",
      "description": "Python web frameworks"
    }
  ]
}
```

### Scheduler Configuration

The random interval sync is configured in `src/github_stars/scheduler.py`:

```python
import random

# Sync interval: random between 30-120 seconds
interval = random.randint(30, 120)
```

---

## Troubleshooting

### Application Won't Start

**Check:**
1. Virtual environment activated
2. Dependencies installed
3. `.env` file configured with GitHub token
4. Database directory exists

**Solution:**
```bash
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data
python src/github_stars/app.py
```

### Dark Mode Not Working

**Check:**
1. Browser console for JavaScript errors
2. CSS file loaded correctly
3. localStorage enabled in browser

**Solution:**
```javascript
// Clear localStorage and refresh
localStorage.removeItem('dashboard-theme')
location.reload()
```

### Sync Not Updating Stars

**Check:**
1. GitHub token has correct permissions
2. API rate limit not exceeded
3. Repository URLs are correct

**Solution:**
```bash
# Test GitHub API directly
curl -H "Authorization: token YOUR_TOKEN" \
  https://api.github.com/repos/torvalds/linux

# Check app logs
grep "GitHub API" data/app.log
```

### Database Errors

**Check:**
1. Database file exists
2. File permissions correct
3. No database lock

**Solution:**
```bash
# Check database
ls -la data/github_stars.db

# Fix permissions
chmod 644 data/github_stars.db

# Restart application
```

---

## Project Phases Summary

### Phase 1: Database Layer ✅ Complete
- Database setup and configuration
- SQLAlchemy models implementation
- Configuration management

### Phase 2: Core Functionality ✅ Complete
- GitHub API client integration
- Auto-categorization engine
- Data synchronization logic

### Phase 3: API & CLI ✅ Complete
- RESTful API endpoints
- Command-line interface
- Error handling and validation

### Phase 4: Frontend Development ✅ Complete
- Responsive dashboard UI
- Real-time statistics display
- Repository management interface

### Phase 5: Monitoring & Logging ✅ Complete
- Structured logging system
- Activity tracking
- Health monitoring
- Consolidated package structure

### Phase 6: Containerization & Dark Mode ✅ Complete
- Docker containerization
- Dark mode UI implementation
- Theme persistence

---

## Version History

### v1.0.0 (2026-04-17)
- Initial release
- Complete feature set
- Dark mode support
- Containerization

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

---

## License

This project is licensed under the MIT License.

---

## Support

For issues and feature requests, please open an issue in the repository.

---

*Last Updated: 2026-04-17*
