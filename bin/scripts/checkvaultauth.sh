#!/bin/bash

if [[ -z "$1" ]]; then
  echo "Usage: $0 <kubeconfig_file>"
  exit 1
fi
OCPCLUSTER=$1
FAILED=0

export KUBECONFIG=${OCPCLUSTER}
export OC="oc"
CKHOST=$(${OC} config view --minify -ojsonpath='{.clusters[0].cluster.server}' | cut -d '/' -f3 |cut -d ':' -f1)
nc -z -w5 "${CKHOST}" 6443
status=$?
if [[ ${status} -eq 0 ]] ; then
  PXNS=$(${OC} get namespace portworx --no-headers --output=go-template='{{.metadata.name}}' 2>/dev/null)
  if [[ -n "${PXNS}" ]]
  then
    # Check for vault-auth-* or px-vault-auth-* secrets
    VAULT_SECRETS=$(${OC} get secrets -n "${PXNS}" -o custom-columns=NAME:.metadata.name --no-headers 2>/dev/null | grep -E '^(vault-auth-|px-vault-auth-)' || true)
    if [[ -z "${VAULT_SECRETS}" ]]; then
      echo "Error: No vault-auth-* or px-vault-auth-* secrets found in namespace ${PXNS} on cluster ${OCPCLUSTER}"
      exit 1
    fi

    PXSTC=$(${OC} get stc -n portworx --no-headers -o name 2>/dev/null)
    if [[ -n "${PXSTC}" ]]
    then
      echo "NS:${PXNS} CLUSTER:${OCPCLUSTER} STC:${PXSTC}"
      PXTOKEN=$(${OC} -n portworx get secrets px-admin-token -ojsonpath='{.data.auth-token}' | base64 -d )
      for PXSTCPOD in $(${OC} get pods -n portworx --selector='name==portworx' -o name --no-headers)
      do
        S3VAL=$(${OC} -n portworx -c portworx exec -it "${PXSTCPOD}" -- bash -c "export PXCTL_AUTH_TOKEN=${PXTOKEN} && /opt/pwx/bin/pxctl credentials validate px-snap-creds" 2>&1)
        if [[ ! "${S3VAL}" =~ "successfully" ]]
        then
          STCNODE=$(${OC} get -n portworx -o json "${PXSTCPOD}" |jq -er '.spec.nodeName')
          echo "node: ${STCNODE} pod ${PXSTCPOD}  validate: ${S3VAL}"
          FAILED=1
          #break
          else
          echo "pod ${PXSTCPOD} verified"
        fi
      done
    fi
  fi
fi
if [[ ${FAILED} -eq 1 ]]
then
  echo "${OCPCLUSTER} failed"
  exit 1
fi