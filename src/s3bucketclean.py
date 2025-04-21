#!/usr/bin/env python3
"""S3 Bucket Cleanup Tool.

This script helps clean up old objects in S3-compatible storage buckets based on retention days.
It supports both current and versioned objects, and can work with specific prefixes.

Example Usage:
    python s3bucketclean.py --access-key-id="access-key" \
        --secret-access-key="secret-key" \
        --endpoint="https://s3.us-west-1.wasabisys.com" \
        --bucket="my-bucket" \
        --prefix="" \
        --delete-after-retention-days=5
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

import typer
from boto3 import client
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/s3_cleanup.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def setup_s3_client(endpoint_url: str, access_key_id: str, secret_access_key: str) -> client:
    """Set up the S3 client with the provided credentials.

    Args:
        endpoint_url: The S3 endpoint URL
        access_key_id: AWS access key ID
        secret_access_key: AWS secret access key

    Returns:
        boto3.client: Configured S3 client

    Raises:
        ClientError: If credentials are invalid
        Exception: For other connection errors
    """
    try:
        s3_client = client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )
        # Verify credentials by listing buckets
        s3_client.list_buckets()
        return s3_client
    except ClientError:
        logger.error("Invalid access or secret key provided")
        raise typer.Exit(1)
    except Exception as e:
        logger.error(f"Failed to create S3 client: {str(e)}")
        raise typer.Exit(1)


def list_objects_to_delete(
    s3_client: client, bucket: str, prefix: str, retention_days: int
) -> tuple[List[Dict], int, int]:
    """List objects that should be deleted based on retention policy.

    Args:
        s3_client: Configured S3 client
        bucket: Name of the bucket
        prefix: Object prefix to filter
        retention_days: Number of days after which objects should be deleted

    Returns:
        tuple: List of objects to delete, count of current versions, count of non-current versions
    """
    today = datetime.now(timezone.utc)
    delete_list = []
    count_current = 0
    count_non_current = 0

    try:
        paginator = s3_client.get_paginator("list_object_versions")
        operation_parameters = {"Bucket": bucket}
        if prefix:
            operation_parameters["Prefix"] = prefix

        logger.info(f"Scanning bucket '{bucket}' for objects older than {retention_days} days")

        for response in paginator.paginate(**operation_parameters):
            if "Versions" not in response:
                continue

            for version in response["Versions"]:
                if version["IsLatest"]:
                    count_current += 1
                else:
                    count_non_current += 1

                if (today - version["LastModified"]).days > retention_days:
                    delete_list.append({"Key": version["Key"], "VersionId": version["VersionId"]})

        return delete_list, count_current, count_non_current
    except Exception as e:
        logger.error(f"Error listing objects: {str(e)}")
        raise typer.Exit(1)


def delete_objects(
    s3_client: client, bucket: str, objects: List[Dict], dry_run: bool = False
) -> None:
    """Delete objects from the bucket in batches.

    Args:
        s3_client: Configured S3 client
        bucket: Name of the bucket
        objects: List of objects to delete
        dry_run: If True, only show what would be deleted without performing deletions
    """
    if not objects:
        logger.info("No objects to delete")
        return

    if dry_run:
        logger.info(f"DRY RUN: Would delete {len(objects)} objects from bucket '{bucket}':")
        for obj in objects:
            logger.info(f"  Would delete: {obj['Key']} (version: {obj['VersionId']})")
        return

    logger.info(f"Deleting {len(objects)} objects from bucket '{bucket}'")
    batch_size = 1000

    try:
        for i in range(0, len(objects), batch_size):
            batch = objects[i : i + batch_size]
            response = s3_client.delete_objects(
                Bucket=bucket, Delete={"Objects": batch, "Quiet": True}
            )

            if "Errors" in response and response["Errors"]:
                for error in response["Errors"]:
                    logger.error(f"Failed to delete object {error['Key']}: {error['Message']}")

            logger.info(f"Deleted batch of {len(batch)} objects")
    except Exception as e:
        logger.error(f"Error deleting objects: {str(e)}")
        raise typer.Exit(1)


def main(
    access_key_id: str = typer.Option(..., "--access-key-id", help="AWS access key ID"),
    secret_access_key: str = typer.Option(..., "--secret-access-key", help="AWS secret access key"),
    endpoint: str = typer.Option(..., "--endpoint", help="S3 endpoint URL"),
    bucket: str = typer.Option(..., "--bucket", help="Bucket name"),
    prefix: str = typer.Option("", "--prefix", help="Object prefix filter"),
    delete_after_retention_days: int = typer.Option(
        15, "--delete-after-retention-days", help="Delete objects older than this many days"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be deleted without performing deletions"
    ),
) -> None:
    """Clean up old objects in an S3-compatible bucket based on retention period.

    If --dry-run is specified, it will only show what would be deleted without performing actual deletions.
    """
    # Set up S3 client
    s3_client = setup_s3_client(endpoint, access_key_id, secret_access_key)

    # List objects to delete and get counts
    delete_list, count_current, count_non_current = list_objects_to_delete(
        s3_client, bucket, prefix, delete_after_retention_days
    )

    # Log initial object counts
    logger.info("-" * 50)
    logger.info("Before deletion:")
    logger.info(f"Current objects: {count_current}")
    logger.info(f"Non-current objects: {count_non_current}")
    logger.info(f"Objects to delete: {len(delete_list)}")
    logger.info("-" * 50)

    # Delete objects (or show what would be deleted in dry-run mode)
    delete_objects(s3_client, bucket, delete_list, dry_run)

    if not dry_run:
        # Get updated counts
        final_list, final_current, final_noncurrent = list_objects_to_delete(
            s3_client, bucket, prefix, delete_after_retention_days
        )

        # Log final object counts
        logger.info("-" * 50)
        logger.info("After deletion:")
        logger.info(f"Current objects: {final_current}")
        logger.info(f"Non-current objects: {final_noncurrent}")
        logger.info("-" * 50)
        logger.info("Cleanup completed successfully")
    else:
        logger.info("-" * 50)
        logger.info("Dry run completed. No files were deleted.")
        logger.info("-" * 50)


if __name__ == "__main__":
    typer.run(main)
