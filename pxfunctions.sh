#!/bin/bash
#
# Script: bash_portworx.sh
# Description: Source this to create portworx functions to use from cmd line
# Usage: source ./nash_portworx.sh
#
# Dependencies:
#   - curl: for API requests
#   - jq: for JSON parsing
#   - nc: for network connectivity checks
#   - oc: for OpenShift/Kubernetes operations
#
# Environment Variables:
#   - VAULT_TOKEN: Optional, vault token for authentication
#   - DEBUG: Optional, set to "true" for debug output
#   - PXCTL_AUTH_TOKEN: Generated auth token for portworx
#   - GOVC_* variables for VMware operations

# Enable strict mode
set -euo pipefail
IFS=$'\n\t'

#######################
# Function Definitions
#######################

# Function: pxnodes
# Description: Get portworx nodes with their labels
# Arguments: None
# Returns: List of nodes with portworx-related labels
# Example: pxnodes
pxnodes() {
    oc get nodes \
        -Ltopology.portworx.io/zone \
        -Ltopology.kubernetes.io/zone \
        -Lportworx.io/node-type \
        -Lpx/service \
        -Lpx/enabled \
        --no-headers
}

# Function: pxpods
# Description: Get portworx pods with storage information
# Arguments: None
# Returns: List of portworx pods with storage details
# Example: pxpods
pxpods() {
    oc get -n"${PX_NS}" po -lname=portworx -Lstorage -owide --no-headers
}

# Function: pxtoken
# Description: Generate and export the PXCTL authentication token
# Arguments: None
# Returns: Export command for PXCTL_AUTH_TOKEN
# Example: pxtoken
pxtoken() {
    echo "export PXCTL_AUTH_TOKEN=\"$(oc -n"${PX_NS}" get secrets px-admin-token -ojsonpath='{.data.auth-token}' | base64 -d)\""
}

# Function: pxkvdb
# Description: Get primary KVDB member
# Arguments: None
# Returns: Node name of primary KVDB member
# Example: pxkvdb
pxkvdb() {
    local PXKVDB1
    PXKVDB1="$(oc get -nkube-system "$(oc get cm -nkube-system -oname | grep px-bootstrap)" \
        -ojsonpath='{.data.px-entries}' | jq -er '.[]|select(.Domain=="portworx-1.internal.kvdb")|.IP')"
    export PXKVDB1
    oc get pod -n"${PX_NS}" -lname=portworx -ojson | \
        jq -re --arg b "${PXKVDB1}" '.items[]|select(.status.hostIP == $b)|.spec.nodeName'
}

# Function: pxlskvdb
# Description: List all KVDB members
# Arguments: None
# Returns: Node names of all KVDB members with their portworx instance number
# Example: pxlskvdb
# Output Example:
#   node1.example.com (portworx-1)
#   node2.example.com (portworx-2)
#   node3.example.com (portworx-3)
pxlskvdb() {
    local PXBOOT_CM kvdb_data node_name
    PXBOOT_CM="$(oc get cm -nkube-system -oname | grep px-bootstrap)"
    
    kvdb_data="$(oc get -nkube-system "${PXBOOT_CM}" -ojsonpath='{.data.px-entries}')"
    
    for i in {1..3}; do
        ip="$(echo "${kvdb_data}" | jq -er ".[] | select(.Domain==\"portworx-${i}.internal.kvdb\") | .IP")"
        if [[ -n "${ip}" ]]; then
            node_name="$(oc get pod -n"${PX_NS}" -lname=portworx -ojson | \
                jq -r --arg ip "${ip}" '.items[] | select(.status.hostIP == $ip) | .spec.nodeName')"
            echo "${node_name} (portworx-${i})"
        else
            echo "No KVDB member found for portworx-${i}"
        fi
    done
}

# Function: pxdebugkvdb
# Description: Debug KVDB setup by opening a debug session on the primary KVDB node
# Arguments: None
# Returns: Opens an interactive debug session
# Example: pxdebugkvdb
pxdebugkvdb() {
    local PXBOOT_CM PXKVDB1 KVDB1
    PXBOOT_CM="$(oc get cm -nkube-system -oname | grep px-bootstrap)"
    PXKVDB1="$(oc get -nkube-system "${PXBOOT_CM}" -ojsonpath='{.data.px-entries}' | \
        jq -er '.[]|select(.Domain=="portworx-1.internal.kvdb")|.IP')"
    export PXKVDB1
    echo "Found KVDB: ${PXKVDB1}"
    KVDB1="$(oc get pod -n"${PX_NS}" -lname=portworx -ojson | \
        jq -re --arg b "${PXKVDB1}" '.items[]|select(.status.hostIP == $b)|.spec.nodeName')"
    export KVDB1
    pxtoken
    oc debug "node/${KVDB1}"
}

# Function: pxpython
# Description: Activate Python virtual environment for Portworx scripts
# Arguments: None
# Returns: Activates the virtual environment
# Example: pxpython
pxpython() {
    # shellcheck disable=SC1091
    source "/.hydra/platform_apps/portworx/portworxscripts/.venv/bin/activate"
}

# Function: pxpythonjit
# Description: Activate Python virtual environment for Portworx JIT scripts
# Arguments: None
# Returns: Activates the JIT virtual environment
# Example: pxpythonjit
pxpythonjit() {
    # shellcheck disable=SC1091
    source "${HOME}/git/portworxscripts/.venv/bin/activate"
}

# Function: pxstgno
# Description: Get storage node information in CSV format
# Arguments: None
# Returns: CSV formatted storage node details including SchedulerNodeName, NodeID, Zone, and Config details
# Example: pxstgno
pxstgno() {
    local PXCDCM
    PXCDCM="$(oc get cm -nkube-system -oname | grep cloud-drive)"
    oc get -nkube-system -ojson "${PXCDCM}" | \
        jq -re '.data."cloud-drive"' | \
        jq -er '.[]|select( .Configs != null )|[ .SchedulerNodeName,.NodeID,.Zone ,(.Configs |.[]|.labels.datastore,.ID)] |@csv'
}

# Function: pxgovc
# Description: Configure govc environment variables for VMware operations
# Arguments: None
# Returns: Sets up required environment variables for govc command and displays VC URL
# Example: pxgovc
pxgovc() {
    local GOVC_USERNAME GOVC_PASSWORD GOVC_URL
    GOVC_USERNAME="$(oc get secrets px-vsphere-secret -ojson -n"${PX_NS}" | \
        jq -r '.data.VSPHERE_USER' | base64 -d)"
    GOVC_PASSWORD="$(oc get secrets px-vsphere-secret -ojson -n"${PX_NS}" | \
        jq -r '.data.VSPHERE_PASSWORD' | base64 -d)"
    GOVC_URL="$(oc get stc -n"${PX_NS}" -ojson | \
        jq -r '.items[0].spec.env[] | select(.name=="VSPHERE_VCENTER") | .value')/sdk"
    GOVC_INSECURE=true
    export GOVC_INSECURE GOVC_PASSWORD GOVC_URL GOVC_USERNAME
    echo "VC:${GOVC_URL}"
}

# Global variables
readonly PX_NS="portworx"
readonly DEBUG="${DEBUG:-false}"

# Check for required commands
for cmd in oc jq curl nc; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: Required command '$cmd' not found"
        return 1
    fi
done
