#!/bin/bash
NAMESPACE="px-backup"
# Define which pods and containers to include
TARGET_PODS=("px-backup-57cd656c76-ftpgf" "pxc-backup-mongodb-0" "pxc-backup-mongodb-1" "pxc-backup-mongodb-2")
TARGET_CONTAINERS=("mongodb" "px-backup")

OUTPUT_FILE="memory_usage_filtered_flexible.csv"

# Create CSV header
echo "timestamp,pod,container,memory_bytes,formatted_memory_mb" > $OUTPUT_FILE

# Get the Prometheus pod
PROMETHEUS_POD=$(oc get pods -n openshift-monitoring -l app.kubernetes.io/name=prometheus -o name | head -1)

# Set time range for 30 days (macOS compatible)
END=$(date +%s)
START=$((END - 30*24*60*60))
STEP=3600

echo "Querying Prometheus for $NAMESPACE namespace pods over 30 days..."
echo "Start time: $(date -j -f %s $START)"
echo "End time: $(date -j -f %s $END)"

# Create a temporary file
TEMP_FILE="/tmp/prometheus_data_$$"

# Fetch data from Prometheus
echo "Fetching data from Prometheus..."
oc exec -it $PROMETHEUS_POD -n openshift-monitoring -- \
  curl -g "http://localhost:9090/api/v1/query_range?query=container_memory_usage_bytes%7Bnamespace%3D%22$NAMESPACE%22%2Cpod%3D~%22${TARGET_PODS[*]}%22%7D&start=$START&end=$END&step=$STEP" > $TEMP_FILE 2>&1

# Check if file was created and has content
if [ -f "$TEMP_FILE" ] && [ -s "$TEMP_FILE" ]; then
    echo "Data fetched successfully. Processing..."
    
    # Process each result properly
    jq -c '.data.result[]' $TEMP_FILE | while read -r result; do
        pod=$(echo "$result" | jq -r '.metric.pod')
        container=$(echo "$result" | jq -r '.metric.container')
        
        # Check if pod is in our target list
        pod_in_target=false
        for target_pod in "${TARGET_PODS[@]}"; do
            if [ "$pod" = "$target_pod" ]; then
                pod_in_target=true
                break
            fi
        done
        
        # Check if container is in our target list
        container_in_target=false
        for target_container in "${TARGET_CONTAINERS[@]}"; do
            if [ "$container" = "$target_container" ]; then
                container_in_target=true
                break
            fi
        done
        
        # Process if either pod or container is in target list
        if [ "$pod_in_target" = true ] || [ "$container_in_target" = true ]; then
            echo "Processing pod: $pod, container: $container"
            
            # Process each timestamp-value pair
            echo "$result" | jq -r '.values[] | "\(.[]),\(.[])"' | while IFS=',' read -r timestamp value; do
                if [ -n "$timestamp" ] && [ -n "$value" ] && [ "$value" != "null" ] && [ "$timestamp" != "null" ]; then
                    readable_time=$(date -j -f %s $timestamp "+%Y-%m-%d %H:%M:%S")
                    memory_mb=$(echo "scale=2; $value/1024/1024" | bc)
                    echo "$readable_time,$pod,$container,$value,$memory_mb"
                fi
            done
        else
            echo "Skipping pod: $pod, container: $container (not in target list)"
        fi
    done >> $OUTPUT_FILE
    
    # Clean up
    rm $TEMP_FILE
    
    echo "Data exported to $OUTPUT_FILE"
    echo "Rows processed: $(wc -l < $OUTPUT_FILE)"
else
    echo "Error: Failed to fetch data from Prometheus"
    if [ -f "$TEMP_FILE" ]; then
        echo "Debug - Content of temp file:"
        cat $TEMP_FILE
        rm $TEMP_FILE
    fi
    exit 1
fi