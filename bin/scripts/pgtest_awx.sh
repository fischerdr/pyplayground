#!/bin/bash

# ==============================================================================
# pgtest_awx.sh
#
# Description:
#   This script tests the connection to the AWX PostgreSQL database,
#   queries the main_credential table, and displays the schemas for
#   credential-related tables.
#
# Configuration:
#   The following environment variables should be set:
#   - PGHOST: The database host (default: localhost)
#   - PGPORT: The database port (default: 5432)
#   - PGDATABASE: The database name (default: awx)
#   - PGUSER: The database user (default: awx)
#   - PGPASSWORD: The database password (default: tower_password)
#
# ==============================================================================

# --- Configuration via environment variables ---
export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="${PGDATABASE:-awx}"
export PGUSER="${PGUSER:-awx}"
export PGPASSWORD="${PGPASSWORD:-tower_password}" # Use a secure vault or injected secret in production

# --- Functions ---

# Test database connectivity and ability to read from main_credential table
test_connection() {
    echo "Testing connection to PostgreSQL at $PGHOST:$PGPORT with user $PGUSER..."

    # SQL query to fetch first 5 credentials
    local sql_query="SELECT id, name, credential_type_id, inputs FROM main_credential LIMIT 5;"

    # Execute the query
    psql -X --set ON_ERROR_STOP=on --no-align --tuples-only -c "$sql_query" 2>&1
    local exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo "✅ Successfully connected and read from main_credential table."
    else
        echo "❌ Failed to connect or read from main_credential table."
        exit 1
    fi
}

# Display the schema for a given table
show_schema() {
    local table_name="$1"
    if [ -z "$table_name" ]; then
        echo "❌ Table name not provided to show_schema function."
        return 1
    fi

    echo ""
    echo "--- Schema for table: $table_name ---"
    psql -X --set ON_ERROR_STOP=on -c "\d $table_name"
    local exit_code=$?

    if [ $exit_code -ne 0 ]; then
        echo "❌ Failed to retrieve schema for table: $table_name"
        return 1
    fi
}

# --- Main execution ---

main() {
    # Check if psql is installed
    if ! command -v psql &>/dev/null; then
        echo "❌ psql command could not be found. Please install PostgreSQL client."
        exit 1
    fi

    test_connection

    echo ""
    echo "Displaying schemas for credential-related tables..."

    show_schema "main_credential"
    show_schema "main_credentialtype"

    echo ""
    echo "✅ Schema review script finished."
}

main "$@"
