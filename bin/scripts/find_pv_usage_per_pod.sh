#!/usr/bin/env bash

set -euo pipefail

echo "pod_name,namespace,pvc_name,num_files,total_size"

# Get all PVCs with the Portworx provisioner
kubectl get pv -o json | jq -r '.items[] | select(.spec.csi.driver=="pxd.portworx.com") | [.metadata.name, .spec.claimRef.name, .spec.claimRef.namespace] | @tsv' | while IFS=$'\t' read -r pv pvc namespace; do
    # Get all pods in the namespace that are using this PVC
    kubectl get pods -n "$namespace" -o json | jq -r --arg pvc "$pvc" '
        .items[] |
        select(.spec.volumes[]?.persistentVolumeClaim.claimName == $pvc) |
        [.metadata.name, (.spec.containers[0].volumeMounts[]? | select(.name == (.spec.volumes[]? | select(.persistentVolumeClaim.claimName == $pvc).name)).mountPath)] |
        @tsv
    ' | while IFS=$'\t' read -r pod mount_path; do
        mount_path=${mount_path:-/mnt}

        # Run commands in the pod to get file count and size
        num_files=$(kubectl exec -n "$namespace" "$pod" -- find "$mount_path" -type f 2>/dev/null | wc -l)
        total_size=$(kubectl exec -n "$namespace" "$pod" -- du -sh "$mount_path" 2>/dev/null | cut -f1)

        echo "$pod,$namespace,$pvc,$num_files,$total_size"
    done
done
