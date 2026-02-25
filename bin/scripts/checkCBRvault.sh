#!/usr/bin/env bash
#
# verify_vault_k8s_auth.sh
#
# Usage: ./verify_vault_k8s_auth.sh <namespace> <serviceaccount>
# Example: ./verify_vault_k8s_auth.sh vault-ns vault-auth
#
# This script verifies:
#   1. ServiceAccount exists in the given namespace
#   2. ClusterRoleBinding exists that links the SA to system:auth-delegator
#   3. The SA token can create TokenReview (using `oc auth can-i`)
#

set -euo pipefail

NS="${1:-}"
SA="${2:-}"

if [[ -z "$NS" || -z "$SA" ]]; then
  echo "Usage: $0 <namespace> <serviceaccount>"
  exit 1
fi

echo "Checking ServiceAccount '$SA' in namespace '$NS'..."

if ! oc -n "$NS" get sa "$SA" &>/dev/null; then
  echo "FAIL: ServiceAccount $SA not found in namespace $NS"
  exit 1
fi
echo "OK: ServiceAccount exists."

echo
echo "Checking ClusterRoleBindings for SA '$NS/$SA'..."
CRBS=$(oc get clusterrolebinding -o json \
  | jq -r --arg ns "$NS" --arg sa "$SA" \
    '.items[] 
     | select(.subjects[]? 
       | .kind=="ServiceAccount" 
       and .name==$sa 
       and .namespace==$ns) 
     | .metadata.name + " -> " + .roleRef.name')

if [[ -z "$CRBS" ]]; then
  echo "FAIL: No ClusterRoleBinding found for $NS/$SA"
  exit 1
fi
echo "OK: Found ClusterRoleBindings:"
echo "$CRBS"

if ! echo "$CRBS" | grep -q "system:auth-delegator"; then
  echo "WARNING: None of the ClusterRoleBindings grant 'system:auth-delegator'."
else
  echo "OK: SA is bound to system:auth-delegator."
fi

echo
echo "Checking token permissions for SA '$NS/$SA'..."
TOKEN=$(oc -n "$NS" create token "$SA" 2>/dev/null || true)

if [[ -z "$TOKEN" ]]; then
  echo "WARNING: Could not fetch token via 'oc create token'."
  echo "         If you are on an older cluster, look at SA secrets manually."
else
  if oc --token="$TOKEN" --namespace="$NS" auth can-i create tokenreviews.authentication.k8s.io &>/dev/null; then
    CAN_I=$(oc --token="$TOKEN" --namespace="$NS" auth can-i create tokenreviews.authentication.k8s.io)
    if [[ "$CAN_I" == "yes" ]]; then
      echo "OK: Token for $NS/$SA can call TokenReview API."
    else
      echo "FAIL: Token for $NS/$SA cannot call TokenReview API."
      exit 1
    fi
  else
    echo "FAIL: Failed to run 'oc auth can-i' with SA token."
    exit 1
  fi
fi

echo
echo "Verification complete for $NS/$SA."
