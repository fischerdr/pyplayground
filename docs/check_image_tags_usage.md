# Docker/Podman Image Tag Checker

## Overview

The `check_image_tags.sh` script is a comprehensive tool for checking Docker and Podman images on your local machine and comparing them with available tags on Docker Hub. This is useful for:

- Identifying outdated images
- Checking if local image tags exist on Docker Hub
- Discovering available tags for specific images
- Managing image versions across Docker and Podman

## Features

- **Multi-runtime support**: Works with both Docker and Podman
- **Docker Hub integration**: Queries Docker Hub API for available tags
- **Update checking**: Identifies available updates for local images
- **Flexible filtering**: Check specific images or all local images
- **Authentication support**: Works with private repositories using Docker Hub credentials
- **Colored output**: Easy-to-read colored terminal output
- **Comprehensive error handling**: Graceful handling of missing dependencies and API failures

## Prerequisites

The script requires the following tools to be installed:

- `docker` (optional, for Docker image checking)
- `podman` (optional, for Podman image checking)
- `jq` (required, for JSON parsing)
- `curl` (required, for API calls)
- `grep` (required, for text processing)
- `sort` (required, for sorting results)

## Usage

### Basic Usage

```bash
# Check all local images (Docker and Podman)
./bin/scripts/check_image_tags.sh

# Check only Docker images
./bin/scripts/check_image_tags.sh -d

# Check only Podman images
./bin/scripts/check_image_tags.sh -p

# Check a specific image
./bin/scripts/check_image_tags.sh nginx

# Check all available tags for a specific image
./bin/scripts/check_image_tags.sh -a nginx
```

### Advanced Usage

```bash
# Use Docker Hub credentials for private repositories
./bin/scripts/check_image_tags.sh -u myusername -t mytoken nginx

# Set credentials via environment variables
export DOCKER_HUB_USERNAME="myusername"
export DOCKER_HUB_TOKEN="mytoken"
./bin/scripts/check_image_tags.sh nginx
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `-h` | Show help message and exit |
| `-d` | Check only Docker images |
| `-p` | Check only Podman images |
| `-a` | Show all available tags for each image (may be slow) |
| `-u username` | Docker Hub username for private repositories |
| `-t token` | Docker Hub access token for private repositories |
| `--debug` | Enable debug logging for troubleshooting |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DOCKER_HUB_USERNAME` | Docker Hub username (alternative to `-u`) |
| `DOCKER_HUB_TOKEN` | Docker Hub access token (alternative to `-t`) |

## Examples

### Example 1: Check All Local Images

```bash
$ ./bin/scripts/check_image_tags.sh
[INFO] [check_image_tags.sh] 2025-01-27 10:30:15 - Fetching local Docker images...
[INFO] [check_image_tags.sh] 2025-01-27 10:30:15 - Found 5 unique local images

Checking: nginx:latest
  ✓ Tag 'latest' exists on Docker Hub

Checking: python:3.9
  ✓ Tag '3.9' exists on Docker Hub

Checking: redis:6.2-alpine
  ✗ Tag '6.2-alpine' not found on Docker Hub

Checking: postgres:13
  ✓ Tag '13' exists on Docker Hub

[INFO] [check_image_tags.sh] 2025-01-27 10:30:20 - Image tag check completed
```

### Example 2: Check Specific Image with All Tags

```bash
$ ./bin/scripts/check_image_tags.sh -a nginx
[INFO] [check_image_tags.sh] 2025-01-27 10:35:00 - Checking specific image: nginx
Found 156 tags for 'nginx' on Docker Hub:
latest
1.21.6
1.21.6-alpine
1.22.0
1.22.0-alpine
...
```

### Example 3: Check Only Podman Images

```bash
$ ./bin/scripts/check_image_tags.sh -p
[INFO] [check_image_tags.sh] 2025-01-27 10:40:00 - Fetching local Podman images...
[INFO] [check_image_tags.sh] 2025-01-27 10:40:00 - Found 3 unique local images

Checking: quay.io/prometheus/prometheus:v2.40.0
  ✓ Tag 'v2.40.0' exists on Docker Hub
```

### Example 4: Check for Updates

```bash
$ ./bin/scripts/check_image_tags.sh --updates
[INFO] [check_image_tags.sh] 2025-01-27 10:45:00 - Checking for available updates on local images...
[INFO] [check_image_tags.sh] 2025-01-27 10:45:00 - Fetching local Docker images...
[INFO] [check_image_tags.sh] 2025-01-27 10:45:00 - Fetching local Podman images...
[INFO] [check_image_tags.sh] 2025-01-27 10:45:00 - Found 3 unique local images to check for updates

Checking updates for: nginx:1.21.6
  🔄 Update available: 1.21.6 → 1.25.3

Checking updates for: redis:6.2-alpine
  ✓ Already up to date

Checking updates for: postgres:13
  🔄 Update available: 13 → 16.2

=== Update Summary ===
Up to date: 1
Updates available: 2
Total checked: 3
```

### Example 5: Debug Mode

```bash
$ ./bin/scripts/check_image_tags.sh --debug nginx
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 - Starting main execution with settings:
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 -   CHECK_DOCKER=true
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 -   CHECK_PODMAN=true
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 -   DEBUG_MODE=1
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 -   SPECIFIC_IMAGE=nginx
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 - No Docker Hub credentials provided, using public API
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 - Fetching tags for image: nginx
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 - Normalized image name to: library/nginx
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 - Using public API request for library/nginx
[DEBUG] [check_image_tags.sh] 2025-01-27 10:45:00 - Successfully fetched 156 tags for library/nginx
[INFO] [check_image_tags.sh] 2025-01-27 10:45:00 - Checking specific image: nginx
Found 156 tags for 'nginx' on Docker Hub:
latest
1.21.6
1.21.6-alpine
...
```

## Output Interpretation

### Status Indicators

- **✓** (Green): Tag exists on Docker Hub or already up to date
- **✗** (Red): Tag not found on Docker Hub
- **🔄** (Blue): Update available
- **?** (Yellow): Could not fetch tags from Docker Hub

### Color Coding

- **Blue**: Information messages and headers
- **Green**: Success messages and existing tags
- **Red**: Error messages and missing tags
- **Yellow**: Warning messages and available tags
- **Cyan**: Image names being checked
- **Purple**: Additional information

## Error Handling

The script handles various error conditions gracefully:

- **Missing dependencies**: Reports which tools are missing and exits
- **Docker/Podman not running**: Warns and continues with available runtime
- **API failures**: Warns about failed API calls and continues
- **Invalid credentials**: Falls back to public API access
- **Rate limiting**: Handles Docker Hub API rate limits

## Performance Considerations

- The script uses Docker Hub's public API which has rate limits
- Checking all tags (`-a` flag) can be slow for images with many tags
- The script limits tag display to 20 tags by default to avoid overwhelming output
- Consider using credentials for better API rate limits

## Troubleshooting

### Common Issues

1. **"Docker is not installed or not in PATH"**
   - Install Docker or ensure it's in your PATH
   - Use `-p` flag to check only Podman images

2. **"Podman is not installed or not in PATH"**
   - Install Podman or ensure it's in your PATH
   - Use `-d` flag to check only Docker images

3. **"Missing required dependencies"**
   - Install missing tools: `jq`, `curl`, `grep`, `sort`

4. **"Could not fetch tags from Docker Hub"**
   - Check internet connectivity
   - Verify image name is correct
   - Consider using credentials for private repositories

### Debug Mode

Use the `--debug` flag to enable detailed logging that shows the script's internal operations:

```bash
./bin/scripts/check_image_tags.sh --debug nginx
```

Debug mode provides detailed information about:

- Script configuration and settings
- Image collection process
- Docker Hub API requests
- Image parsing and tag checking
- Error conditions and fallbacks

## Integration

This script can be integrated into:

- CI/CD pipelines for image validation
- Automated maintenance scripts
- Docker/Podman management workflows
- Security scanning processes

## Security Notes

- Docker Hub tokens are sensitive credentials
- Use environment variables instead of command line arguments when possible
- Tokens should have minimal required permissions
- Consider using Docker Hub's official CLI tools for production environments

## Contributing

When modifying this script:

- Follow the existing coding style and structure
- Add appropriate error handling
- Update documentation for new features
- Test with both Docker and Podman
- Ensure compatibility with different shell environments
