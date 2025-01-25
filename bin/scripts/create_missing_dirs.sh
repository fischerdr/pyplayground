#!/bin/bash

# Script to create missing project directories
# Save this as: bin/scripts/create_missing_dirs.sh

# Function to create directory with .gitkeep
create_dir_with_gitkeep() {
    mkdir -p "$1"
    touch "$1/.gitkeep"
    echo "Created directory: $1"
}

# Create template directories
create_dir_with_gitkeep "templates/k8s"
create_dir_with_gitkeep "templates/scripts"
create_dir_with_gitkeep "templates/config"
create_dir_with_gitkeep "templates/docs"

# Create tmp directories
create_dir_with_gitkeep "tmp/cache"
create_dir_with_gitkeep "tmp/downloads"
create_dir_with_gitkeep "tmp/build"

# Create tests directory if it doesn't exist
create_dir_with_gitkeep "tests"

# Update .gitignore if needed
if ! grep -q "tmp/" .gitignore; then
    cat >> .gitignore << EOL

# Temporary Files
tmp/*
!tmp/.gitkeep
!tmp/*/
tmp/cache/*
!tmp/cache/.gitkeep
tmp/downloads/*
!tmp/downloads/.gitkeep
tmp/build/*
!tmp/build/.gitkeep
*.tmp
*.temp
*~
EOL
    echo "Updated .gitignore with tmp patterns"
fi

echo "Directory structure update complete!"