# Benchmarking Kubernetes API Server and etcd Load

This document provides Prometheus queries (PromQL) to help benchmark the impact of resource counting scripts (like `k8s_rcrscountsize.py` and its threaded version) on the Kubernetes API server and the underlying etcd cluster.

## Purpose

Running scripts that make numerous API calls, especially across many namespaces or when fetching full object manifests (for size calculation), can significantly load the cluster's control plane. Monitoring key metrics before, during, and after script execution helps quantify this impact, allowing for informed decisions about script parameters (e.g., concurrency levels) and scheduling.

## Prerequisites & Assumptions

* A Prometheus instance actively scraping metrics from your Kubernetes cluster.
* A metrics setup (like `kube-prometheus-stack`) that exposes standard metrics for the API server and etcd.
* **Label Adjustment:** You **must** verify and adjust the job labels (e.g., `job="apiserver"`, `job="etcd"`) and potentially other labels (`instance`, `pod`, `namespace`) in the queries below to match your specific Prometheus configuration. Use the Prometheus UI explorer to identify the correct labels for your environment.

## I. API Server Metrics

Focus on the load and performance of the Kubernetes API server(s).

1. **API Server Request Rate (Total):**
    * _Purpose:_ Overall rate of requests hitting the API server. Expect an increase during script execution.
    * _Query:_

        ```promql
        sum(rate(apiserver_request_total{job="apiserver"}[5m]))
        ```

2. **API Server Request Rate by Verb (LIST/GET):**
    * _Purpose:_ Rate of specific read operations heavily used by the script.
    * _Query:_

        ```promql
        sum(rate(apiserver_request_total{job="apiserver", verb=~"LIST|GET"}[5m])) by (verb)
        ```

3. **API Server Request Latency (99th Percentile):**
    * _Purpose:_ Latency for the slowest requests. Increases indicate the API server is potentially struggling.
    * _Query:_

        ```promql
        histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{job="apiserver"}[5m])) by (verb, resource, le))
        ```

    * _Note:_ Consider filtering by verb (`verb="GET"`) or resource if needed.

4. **API Server Error Rate (5xx):**
    * _Purpose:_ Rate of server-side errors. An increase indicates problems.
    * _Query:_

        ```promql
        sum(rate(apiserver_request_total{job="apiserver", code=~"5.."}[5m]))
        ```

5. **API Server CPU Usage:**
    * _Purpose:_ CPU resources consumed by the API server.
    * _Query:_

        ```promql
        sum(rate(process_cpu_seconds_total{job="apiserver"}[5m]))
        ```

    * _Note:_ Adapt label selectors if `job="apiserver"` is insufficient.

6. **API Server Memory Usage:**
    * _Purpose:_ Memory footprint of the API server.
    * _Query:_

        ```promql
        sum(process_resident_memory_bytes{job="apiserver"})
        ```

    * _Note:_ Adapt label selectors as needed.

## II. etcd Metrics

Focus on the load and performance of the etcd cluster backing the API server.

1. **etcd gRPC Request Rate (Total):**
    * _Purpose:_ Overall request rate hitting etcd servers.
    * _Query:_

        ```promql
        sum(rate(grpc_server_handled_total{job="etcd"}[5m]))
        ```

2. **etcd Read Request Rate (Range RPCs):**
    * _Purpose:_ Rate of read requests used by the API server for LIST/GET operations.
    * _Query:_

        ```promql
        sum(rate(grpc_server_handled_total{job="etcd", grpc_service="etcdserverpb.KV", grpc_method="Range"}[5m]))
        ```

3. **etcd Request Latency (99th Percentile):**
    * _Purpose:_ Latency of requests handled by etcd. Increases indicate etcd load.
    * _Query:_

        ```promql
        histogram_quantile(0.99, sum(rate(grpc_server_handling_seconds_bucket{job="etcd"}[5m])) by (grpc_method, le))
        ```

    * _Note:_ Pay close attention to the `Range` method latency.

4. **etcd Disk Sync Duration (WAL fsync - 99th Percentile):**
    * _Purpose:_ Write-Ahead Log sync latency. High read load can sometimes impact write performance.
    * _Query:_

        ```promql
        histogram_quantile(0.99, sum(rate(etcd_disk_wal_fsync_duration_seconds_bucket{job="etcd"}[5m])) by (le))
        ```

5. **etcd CPU Usage:**
    * _Purpose:_ CPU resources consumed by etcd.
    * _Query:_

        ```promql
        sum(rate(process_cpu_seconds_total{job="etcd"}[5m]))
        ```

    * _Note:_ Adapt label selectors if `job="etcd"` is insufficient.

6. **etcd Memory Usage:**
    * _Purpose:_ Memory footprint of etcd.
    * _Query:_

        ```promql
        sum(process_resident_memory_bytes{job="etcd"})
        ```

    * _Note:_ Adapt label selectors as needed.

## How to Use for Benchmarking

1. **Establish Baseline:** Run the queries when the cluster is under normal load (before running the script) to understand typical metric values.
2. **Monitor During Script Run:** Execute the queries periodically (e.g., every minute) _while_ the script is running. Use a dashboarding tool like Grafana connected to Prometheus for easier visualization over time.
3. **Compare Results:** Compare the metrics observed during the script run against the baseline. Look for significant increases (or delta) in request rates, latencies, error rates, and resource utilization (CPU/Memory) for both the API server and etcd.
4. **Test Variations:** Use this process to compare different scenarios:
    * Sequential script (`k8s_rcrscountsize.py`) vs. Threaded script (`k8s_rcrscountsize_threaded.py`).
    * Different values for `--max-workers` in the threaded script.
    * Running with and without `--include-crds`.
    * Running with and without `--sizes-only`.
    * Targeting all namespaces vs. using `--label-selector` or `--namespace`.
5. **Adjust Time Range:** Modify the time range window (e.g., `[5m]`) in the `rate()` and `histogram_quantile()` functions based on the expected duration of your script runs and the desired granularity of the metrics.

This comparative data will provide quantitative insights into the script's impact, helping you optimize its usage and parameters for your specific environment.
