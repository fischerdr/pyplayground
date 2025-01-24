#!/usr/bin/env bash

# can be added to ~/.bashrc
update_kubeconfigs() {
  ### Update kubeconfig file based on the individual files on the $config_dir
  local config_dir="${1:-$HOME/.kube/config.d}"
  local backup_files_to_keep="${2:-10}"
  local config_file="$HOME/.kube/config"
  local newer_files current_context kubeconfig_files
  ###
  if [[ ! -d "$config_dir" ]]; then mkdir "$config_dir" -p -v ; fi
  if [[ -f "$config_file" ]]; then
    newer_files=$(find "$config_dir" -newer "$config_file" -type f)
  else
    newer_files=$(find "$config_dir" -type f)
  fi
  # Only if there were files newer than the existing config_file
  if [[ -n "$newer_files" ]]; then
    current_context=$(kubectl config current-context) # Save last context
    # Backup existing config file and remove old backups
    cp -a "$config_file" "${config_file}_$(date +"%Y-%m-%d-%H%M%S")"
    find "${config_file%/*}" -maxdepth 1 -name "config_*" -type f -printf '%Ts\t%p\n' \
      | sort -n | head -n "-$backup_files_to_keep" | cut -f 2- | xargs rm -f
    # Remove contexts if they have changed to force updates
    for file in $newer_files; do
      context_name=$(kubectl config get-contexts --kubeconfig "$file" --no-headers|awk '{print $1}')
      context_cluster=$(kubectl config get-contexts --kubeconfig "$file" --no-headers|awk '{print $2}')
      context_user=$(kubectl config get-contexts --kubeconfig "$file" --no-headers|awk '{print $3}')
      if kubectl config get-contexts | grep "$context_name" -q; then
        kubectl config delete-context "$context_name"
        kubectl config unset "contexts.$context_name"
        kubectl config unset "clusters.$context_cluster"
        kubectl config unset "users.$context_user"
      fi
    done
    # Create new config file
    kubeconfig_files="$config_file:$(find "$HOME/.kube/config.d/" -type f | tr '\n' ':')"
    KUBECONFIG="$kubeconfig_files" kubectl config view --merge --flatten > "$HOME/.kube/tmp"
    #install -m 600 "$HOME/.kube/tmp" $config_file
    mv "$HOME/.kube/tmp" "$config_file" && chmod 600 "$config_file"
    export KUBECONFIG=$config_file
    kubectl config use-context "$current_context" --namespace=default
  fi
}

update_kubeconfigs "$HOME/.kube/config.d" 10 # keep 10 most recent backup