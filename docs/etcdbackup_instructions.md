# Dockerfile to create an image that can handle the etcd backup operation described earlier

This Dockerfile includes etcdctl for interacting with etcd and the AWS CLI for uploading backups to S3

## Dockerfile

```dockerfile
# Use a lightweight base image
FROM alpine:3.18
# Install necessary tools: etcdctl, aws-cli, and bash
RUN apk add --no-cache \
    etcd \
    aws-cli \
    bash \
    curl \
    ca-certificates && \
    mkdir -p /certs /scripts /data && \
    chmod +x /scripts
# Set working directory
WORKDIR /scripts
# Copy the backup script into the container
COPY etcd-backup.sh /scripts/etcd-backup.sh
# Make the backup script executable
RUN chmod +x /scripts/etcd-backup.sh
# Set environment variables (these can be overridden at runtime)
ENV ETCD_ENDPOINT=<https://127.0.0.1:2379>
ENV ETCD_CERT_FILE=/certs/etcd-client.crt
ENV ETCD_KEY_FILE=/certs/etcd-client.key
ENV ETCD_CA_FILE=/certs/etcd-ca.crt
ENV S3_BUCKET=my-etcd-backups
ENV S3_ENDPOINT=<https://s3.amazonaws.com>
ENV BACKUP_INTERVAL=3600
# Command to start the backup process
CMD ["/scripts/etcd-backup.sh"]
```

## Backup script to include in the container (etcd-backup.sh)

```bash
#!/bin/bash
set -e
echo "Starting etcd backup service..."
echo "ETCD Endpoint: $ETCD_ENDPOINT"
echo "S3 Bucket: $S3_BUCKET"
echo "Backup Interval: $BACKUP_INTERVAL seconds"

while true; do
  TIMESTAMP=$(date +%Y%m%d%H%M%S)
  BACKUP_FILE="/data/etcd-backup-${TIMESTAMP}.db"
  
  echo "Creating etcd snapshot..."
  etcdctl --endpoints="${ETCD_ENDPOINT}" \
          --cert="${ETCD_CERT_FILE}" \
          --key="${ETCD_KEY_FILE}" \
          --cacert="${ETCD_CA_FILE}" \
          snapshot save "${BACKUP_FILE}"

  echo "Uploading snapshot to S3..."
  aws s3 cp "${BACKUP_FILE}" "s3://${S3_BUCKET}/etcd-backup-${TIMESTAMP}.db" --endpoint-url="${S3_ENDPOINT}"

  echo "Backup completed and uploaded. Sleeping for ${BACKUP_INTERVAL} seconds..."
  rm -f "${BACKUP_FILE}"
  sleep "${BACKUP_INTERVAL}"
done
```

## Build and Use Instructions

  Save the Dockerfile and etcd-backup.sh in the same directory.
  Build the Docker image:

```bash
docker build -t my-etcd-backup:latest .
```

### Run the container locally for testing

```bash
docker run -d \
  -e ETCD_ENDPOINT=https://<ETCD-ENDPOINT>:2379 \
  -e S3_BUCKET=my-etcd-backups \
  -e AWS_ACCESS_KEY_ID=<YOUR_AWS_ACCESS_KEY> \
  -e AWS_SECRET_ACCESS_KEY=<YOUR_AWS_SECRET_KEY> \
  -v /path/to/certs:/certs:ro \
  my-etcd-backup:latest
```

  **Note:** Replace ETCD-ENDPOINT, YOUR_AWS_ACCESS_KEY, and YOUR_AWS_SECRET_KEY with your actual values.

### Key Features

- Base Image: Uses a lightweight Alpine Linux image for minimal size.
- Certs Handling: Supports mounting certificates for secure etcd communication.
- Environment Variables: Configurable at runtime to adapt to different environments.
- AWS CLI: Enables uploading to S3-compatible object stores.

#### Below is a Kubernetes deployment YAML configuration that uses the custom Docker image

```yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: etcd-backup
  namespace: kube-system
  labels:
    app: etcd-backup
spec:
  replicas: 1
  selector:
    matchLabels:
      app: etcd-backup
  template:
    metadata:
      labels:
        app: etcd-backup
    spec:
      containers:
      - name: etcd-backup
        image: my-etcd-backup:latest # Replace with your Docker image name
        imagePullPolicy: Always
        env:
        - name: ETCD_ENDPOINT
          value: https://<ETCD-ENDPOINT>:2379 # Replace with your etcd endpoint
        - name: ETCD_CERT_FILE
          value: /certs/etcd-client.crt
        - name: ETCD_KEY_FILE
          value: /certs/etcd-client.key
        - name: ETCD_CA_FILE
          value: /certs/etcd-ca.crt
        - name: S3_BUCKET
          value: my-etcd-backups # Replace with your S3 bucket name
        - name: S3_ENDPOINT
          value: <https://s3.amazonaws.com> # Replace with your S3 endpoint
        - name: AWS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: s3-credentials
              key: access_key
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: s3-credentials
              key: secret_key
        - name: BACKUP_INTERVAL
          value: "3600" # Backup interval in seconds (e.g., 3600 = 1 hour)
        volumeMounts:
        - name: etcd-certs
          mountPath: /certs
          readOnly: true
        - name: etcd-data
          mountPath: /data
        resources:
          requests:
            memory: "128Mi"
            cpu: "250m"
          limits:
            memory: "256Mi"
            cpu: "500m"
      volumes:
      - name: etcd-certs
        secret:
          secretName: etcd-client-certs # Update with the name of the Secret containing etcd certs
      - name: etcd-data
        emptyDir: {} # Temporary storage for etcd snapshot files
---
apiVersion: v1
kind: Secret
metadata:
  name: s3-credentials
  namespace: kube-system
type: Opaque
data:
  access_key: <BASE64_ENCODED_ACCESS_KEY> # Replace with base64-encoded AWS Access Key
  secret_key: <BASE64_ENCODED_SECRET_KEY> # Replace with base64-encoded AWS Secret Key
---
apiVersion: v1
kind: Secret
metadata:
  name: etcd-client-certs
  namespace: kube-system
type: Opaque
data:
  etcd-client.crt: <BASE64_ENCODED_ETCD_CLIENT_CERT> # Replace with base64-encoded etcd client cert
  etcd-client.key: <BASE64_ENCODED_ETCD_CLIENT_KEY> # Replace with base64-encoded etcd client key
  etcd-ca.crt: <BASE64_ENCODED_ETCD_CA_CERT> # Replace with base64-encoded etcd CA cert
```

### Key Configuration Details

- Image: Uses my-etcd-backup:latest, the image created earlier. Replace with your registry if needed (e.g., your-registry/my-etcd-backup:latest).
- Environment Variables: Configures etcd endpoint, S3 bucket, and credentials.
- Secrets:
  - s3-credentials: Stores AWS credentials for accessing the S3 bucket.
  - etcd-client-certs: Stores etcd client certificates to connect securely to etcd.
- Volumes:
  - Certs: Mounts etcd client certificates from the secret.
  - Data: Temporary in-container storage for backup files before uploading to S3.

#### Steps to Apply

1. Replace ETCD-ENDPOINT and BASE64_ENCODED_... placeholders with your actual values.
2. Apply the YAML to the cluster:

```bash
kubectl apply -f etcd-backup-deployment.yaml
```

#### Verify the deployment

```bash
kubectl get pods -n kube-system
kubectl logs -n kube-system <etcd-backup-pod-name>
```

This configuration ensures that your deployment securely backs up etcd and uploads snapshots to an S3-compatible object store.
