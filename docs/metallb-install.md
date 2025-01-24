# MetalLB Installation Guide

## Overview

This guide provides instructions for installing and configuring MetalLB in a Kubernetes cluster, along with the necessary configuration for the NGINX ingress controller.

## Installation Steps

### 1. Install MetalLB using Helm

```bash
# Add MetalLB Helm repository
helm repo add metallb https://metallb.github.io/metallb

# Install MetalLB
helm install metallb metallb/metallb --create-namespace --namespace metallb
```

### 2. Configure kube-proxy

```bash
# Edit kube-proxy configuration
kubectl edit configmap -n kube-system kube-proxy
```

### 3. Install NGINX Ingress Controller

```bash
helm upgrade --install ingress-nginx ingress-nginx \
  --repo https://kubernetes.github.io/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace
```

## Configuration

### IP Address Pool Configuration

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: first-pool
  namespace: metallb
spec:
  addresses:
    - 192.168.101.190-192.168.101.210
  autoAssign: true
  avoidBuggyIPs: false
```

### L2 Advertisement Configuration

```yaml
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: first-pool-advert
  namespace: metallb
spec:
  ipAddressPools:
  - first-pool
```

### Example Service Configuration

This example shows how to configure a LoadBalancer service for the Rook-Ceph dashboard:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rook-ceph-mgr-dashboard-loadbalancer
  namespace: rook-ceph
  labels:
    app: rook-ceph-mgr
    rook_cluster: rook-ceph
spec:
  ports:
    - name: dashboard
      port: 8443
      protocol: TCP
      targetPort: 8443
  selector:
    app: rook-ceph-mgr
    mgr_role: active
    rook_cluster: rook-ceph
  sessionAffinity: None
  type: LoadBalancer
```

## Additional Resources

- [MetalLB Installation Documentation](https://metallb.universe.tf/installation/)
- [NGINX Ingress Controller Installation Guide](https://kubernetes.github.io/ingress-nginx/deploy/#bare-metal-clusters)
