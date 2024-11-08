#!/bin/bash

NAMESPACE="$1"
KUBE_API="https://kubernetes.default.svc"
TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
CACERT=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

# Validate namespace input
if [[ -z "$NAMESPACE" ]]; then
    echo "Usage: $0 <namespace>"
    exit 1
fi

# Function to check if a string is valid JSON
is_json() {
    echo "$1" | jq empty > /dev/null 2>&1
}

# Retrieve the list of resources specified in ApplicationRegistration
get_application_resources() {
    curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" "$KUBE_API/apis/stork.libopenstorage.org/v1alpha1/applicationregistrations" |
    jq -r '.items[] | select(.resources != null) | .resources[] | "\(.group)/\(.version)/\(.kind)"'
}

# Retrieve core resources excluding PVCs and Pods
get_core_resources() {
    core_resources=("configmaps" "services" "secrets" "replicationcontrollers" "endpoints" "serviceaccounts" "resourcequotas" "limitranges")
    
    for resource in "${core_resources[@]}"; do
        api_path="$KUBE_API/api/v1/namespaces/$NAMESPACE/$resource"
        response=$(curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" "$api_path")
        
        if is_json "$response" && [[ $(echo "$response" | jq '.items | length') -gt 0 ]]; then
            echo "$resource instances in namespace $NAMESPACE:"
            echo "$response" | jq -r --arg resource "$resource" '.items[] | "\($resource): \(.metadata.name)"'
        fi
    done
}

# Retrieve apps resources excluding PVCs and Pods
get_apps_resources() {
    apps_resources=("deployments" "statefulsets" "daemonsets" "replicasets")
    
    for resource in "${apps_resources[@]}"; do
        api_path="$KUBE_API/apis/apps/v1/namespaces/$NAMESPACE/$resource"
        response=$(curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" "$api_path")
        
        if is_json "$response" && [[ $(echo "$response" | jq '.items | length') -gt 0 ]]; then
            echo "$resource instances in namespace $NAMESPACE:"
            echo "$response" | jq -r --arg resource "$resource" '.items[] | "\($resource): \(.metadata.name)"'
        fi
    done
}

# Retrieve data for resources listed in ApplicationRegistration
get_application_registration_resources() {
    for resource in $(get_application_resources); do
        IFS="/" read -r group version kind <<< "$resource"
        api_path="$KUBE_API/apis/$group/$version/namespaces/$NAMESPACE/$(echo "$kind" | tr '[:upper:]' '[:lower:]')s"
        
        response=$(curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" "$api_path")
        
        if is_json "$response" && [[ $(echo "$response" | jq '.items | length') -gt 0 ]]; then
            echo "$kind instances in namespace $NAMESPACE:"
            echo "$response" | jq -r --arg kind "$kind" '.items[] | "\($kind): \(.metadata.name)"'
        fi
    done
}

# Retrieve namespaced resources from custom APIs excluding Pods and PVCs
get_all_resources() {
    curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" "$KUBE_API/apis" |
    jq -r '.groups[].versions[].groupVersion' | while read -r groupVersion; do
        resources=$(curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" "$KUBE_API/apis/$groupVersion" |
            jq -r '.resources[] | select(.namespaced == true and .name != "pods" and .name != "persistentvolumeclaims") | .name')
        
        for resource in $resources; do
            echo "$groupVersion:$resource"
        done
    done
}

# Retrieve data for all other custom resources in the specified namespace
get_all_custom_resources_data() {
    for resource in $(get_all_resources); do
        IFS=":" read -r groupVersion resourceName <<< "$resource"
        api_path="$KUBE_API/apis/$groupVersion/namespaces/$NAMESPACE/$resourceName"
        
        response=$(curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" "$api_path")
        
        if is_json "$response" && [[ $(echo "$response" | jq '.items | length') -gt 0 ]]; then
            echo "$resourceName instances in namespace $NAMESPACE:"
            echo "$response" | jq -r --arg resourceName "$resourceName" '.items[] | "\($resourceName): \(.metadata.name)"'
        fi
    done
}

# Run function to gather and print resources
get_core_resources              # Get core resources
get_apps_resources              # Get apps resources
get_application_registration_resources # Get resources from ApplicationRegistration
get_all_custom_resources_data    # Get other custom resources
