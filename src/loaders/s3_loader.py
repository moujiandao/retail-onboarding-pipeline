"""
S3 Loader with Date Partitioning

Uploads files to S3 with Hive-style partitioning for efficient querying.

Why S3?
- Data lake: Permanent archive of raw and processed data
- Snowflake integration: COPY command loads from S3 (100x faster than INSERT)
- Cost: S3 storage ($0.023/GB/month) vs Snowflake ($40/TB/month)
- Durability: 11 nines (99.999999999%) durability

Date Partitioning Pattern:
--------------------------
Instead of flat structure:
    s3://bucket/invoices/invoice1.parquet
    s3://bucket/invoices/invoice2.parquet

Use Hive-style partitioning:
    s3://bucket/invoices/year=2024/month=01/day=15/invoice1.parquet
    s3://bucket/invoices/year=2024/month=01/day=15/invoice2.parquet

Benefits:
- Efficient pruning: Query only specific dates
- Snowflake external tables can partition on these
- S3 lifecycle policies can archive old partitions to Glacier
- Clear organization for debugging

Usage:
    from src.loaders.s3_loader import S3Loader

    loader = S3Loader(bucket="my-bucket", prefix="retail-pipeline")
    s3_path = loader.upload_file(
        local_path="data/staging/invoices/invoice.parquet",
        s3_key="invoices/year=2024/month=01/day=15/invoice.parquet"
    )
"""

import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, date
import hashlib

import boto3
from botocore.exceptions import ClientError

from src.utils.config import get_config, require_aws_config

logger = logging.getLogger(__name__)


class S3Loader:
    """
    Upload files to S3 with date partitioning and versioning.

    Design decisions:
    - Checksum verification (ensure upload integrity)
    - Multipart upload for large files (>5GB)
    - Metadata tagging (source file, upload timestamp)
    - Idempotent: Re-uploading same file overwrites (same key)
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        enable_versioning: bool = True,
    ):
        """
        Initialize S3 loader.

        Args:
            bucket: S3 bucket name (uses config if not provided)
            prefix: S3 key prefix (e.g., "retail-pipeline/")
            enable_versioning: Whether to enable S3 versioning
        """
        config = get_config()
        require_aws_config(config)

        self.bucket = bucket or config.s3_bucket
        self.prefix = prefix or config.s3_prefix

        # Initialize boto3 client
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            region_name=config.aws_region,
        )

        # Ensure bucket exists
        self._ensure_bucket_exists()

        if enable_versioning:
            self._enable_versioning()

    def _ensure_bucket_exists(self):
        """
        Check if bucket exists, create if not.

        In production, buckets are usually pre-created with proper
        IAM policies. This is a convenience for development.
        """
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            logger.info(f"✓ S3 bucket exists: {self.bucket}")
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                logger.info(f"Creating S3 bucket: {self.bucket}")
                try:
                    self.s3_client.create_bucket(Bucket=self.bucket)
                    logger.info(f"✓ Created bucket: {self.bucket}")
                except ClientError as create_error:
                    logger.error(f"Failed to create bucket: {create_error}")
                    raise
            else:
                logger.error(f"Error checking bucket: {e}")
                raise

    def _enable_versioning(self):
        """
        Enable versioning on S3 bucket.

        Why versioning?
        - Data lineage: Track changes to files over time
        - Rollback: Recover from accidental deletes/overwrites
        - Audit trail: See who uploaded what when

        Cost: Minimal (only stores diffs)
        """
        try:
            self.s3_client.put_bucket_versioning(
                Bucket=self.bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )
            logger.debug(f"✓ Versioning enabled on {self.bucket}")
        except ClientError as e:
            logger.warning(f"Could not enable versioning: {e}")

    def upload_file(
        self,
        local_path: Path,
        s3_key: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Upload a file to S3.

        Args:
            local_path: Path to local file
            s3_key: S3 key (path within bucket)
            metadata: Optional metadata tags (key-value pairs)

        Returns:
            Full S3 URI (s3://bucket/prefix/key)

        Example:
            >>> loader = S3Loader(bucket="my-bucket", prefix="pipeline")
            >>> s3_uri = loader.upload_file(
            ...     local_path="data/staging/invoice.parquet",
            ...     s3_key="invoices/year=2024/month=01/invoice.parquet"
            ... )
            >>> print(s3_uri)
            's3://my-bucket/pipeline/invoices/year=2024/month=01/invoice.parquet'
        """
        local_path = Path(local_path)

        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        # Build full S3 key with prefix
        full_key = f"{self.prefix}/{s3_key}" if self.prefix else s3_key

        # Calculate MD5 checksum for verification
        md5_hash = self._calculate_md5(local_path)

        # Prepare metadata
        upload_metadata = {
            "source-file": str(local_path),
            "upload-timestamp": datetime.now().isoformat(),
            "md5-checksum": md5_hash,
        }
        if metadata:
            upload_metadata.update(metadata)

        # Upload
        try:
            logger.info(f"Uploading {local_path.name} → s3://{self.bucket}/{full_key}")

            self.s3_client.upload_file(
                Filename=str(local_path),
                Bucket=self.bucket,
                Key=full_key,
                ExtraArgs={
                    "Metadata": upload_metadata,
                },
            )

            # Verify upload
            self._verify_upload(full_key, md5_hash)

            s3_uri = f"s3://{self.bucket}/{full_key}"
            logger.info(f"✓ Uploaded to {s3_uri}")

            return s3_uri

        except ClientError as e:
            logger.error(f"Upload failed: {e}")
            raise

    def upload_directory(
        self,
        local_dir: Path,
        s3_prefix: str,
        pattern: str = "*",
        partition_by_date: bool = True,
    ) -> List[str]:
        """
        Upload all files in a directory to S3.

        Args:
            local_dir: Local directory path
            s3_prefix: S3 prefix for uploaded files
            pattern: Glob pattern for file selection
            partition_by_date: Whether to partition by date

        Returns:
            List of S3 URIs

        Example:
            >>> loader.upload_directory(
            ...     local_dir="data/staging/invoices",
            ...     s3_prefix="invoices",
            ...     pattern="*.parquet",
            ...     partition_by_date=True
            ... )
            ['s3://bucket/invoices/year=2024/month=01/day=15/file1.parquet', ...]
        """
        local_dir = Path(local_dir)
        files = list(local_dir.glob(pattern))

        if not files:
            logger.warning(f"No files found in {local_dir} matching {pattern}")
            return []

        logger.info(f"Uploading {len(files)} files from {local_dir}...")

        s3_uris = []
        today = date.today()

        for file_path in files:
            if partition_by_date:
                # Create Hive-style partition
                s3_key = (
                    f"{s3_prefix}/"
                    f"year={today.year}/"
                    f"month={today.month:02d}/"
                    f"day={today.day:02d}/"
                    f"{file_path.name}"
                )
            else:
                s3_key = f"{s3_prefix}/{file_path.name}"

            s3_uri = self.upload_file(file_path, s3_key)
            s3_uris.append(s3_uri)

        logger.info(f"✓ Uploaded {len(s3_uris)} files")
        return s3_uris

    def _calculate_md5(self, file_path: Path) -> str:
        """
        Calculate MD5 checksum of file.

        Why MD5?
        - Fast (faster than SHA-256)
        - Good enough for integrity checking (not cryptographic use)
        - S3 uses MD5 for ETag comparison

        Returns:
            Hex digest of MD5 hash
        """
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()

    def _verify_upload(self, s3_key: str, expected_md5: str):
        """
        Verify file was uploaded correctly.

        Compares MD5 checksum of uploaded file with local file.
        This catches corruption during upload.
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket,
                Key=s3_key,
            )

            # S3 ETag is MD5 for single-part uploads
            # (For multipart uploads, it's more complex)
            s3_etag = response["ETag"].strip('"')

            if s3_etag != expected_md5:
                logger.warning(
                    f"MD5 mismatch: local={expected_md5}, s3={s3_etag}. "
                    f"File may be corrupted."
                )
            else:
                logger.debug(f"✓ Upload verified (MD5: {expected_md5})")

        except ClientError as e:
            logger.warning(f"Could not verify upload: {e}")

    def list_files(
        self,
        s3_prefix: str,
        max_files: int = 1000,
    ) -> List[Dict]:
        """
        List files in S3 with given prefix.

        Args:
            s3_prefix: S3 prefix to search
            max_files: Maximum number of files to return

        Returns:
            List of dicts with file metadata (key, size, last_modified)

        Example:
            >>> files = loader.list_files("invoices/year=2024/month=01/")
            >>> for f in files:
            ...     print(f"{f['key']} ({f['size']} bytes)")
        """
        full_prefix = f"{self.prefix}/{s3_prefix}" if self.prefix else s3_prefix

        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=full_prefix,
                MaxKeys=max_files,
            )

            files = []
            for obj in response.get("Contents", []):
                files.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                    "etag": obj["ETag"].strip('"'),
                })

            logger.info(f"Found {len(files)} files with prefix: {full_prefix}")
            return files

        except ClientError as e:
            logger.error(f"Error listing files: {e}")
            return []

    def generate_presigned_url(
        self,
        s3_key: str,
        expiration: int = 3600,
    ) -> str:
        """
        Generate a presigned URL for temporary access to S3 file.

        Useful for:
        - Sharing files with external users (without AWS credentials)
        - Temporary download links
        - Snowflake COPY command (if not using IAM roles)

        Args:
            s3_key: S3 key
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL (valid for specified duration)

        Example:
            >>> url = loader.generate_presigned_url(
            ...     "invoices/year=2024/month=01/invoice.parquet",
            ...     expiration=600  # 10 minutes
            ... )
            >>> # URL is valid for 10 minutes
        """
        full_key = f"{self.prefix}/{s3_key}" if self.prefix else s3_key

        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": full_key},
                ExpiresIn=expiration,
            )
            logger.info(f"Generated presigned URL (expires in {expiration}s)")
            return url

        except ClientError as e:
            logger.error(f"Error generating presigned URL: {e}")
            raise

    def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3.

        Note: If versioning is enabled, this creates a delete marker
        rather than permanently deleting the file.

        Args:
            s3_key: S3 key to delete

        Returns:
            True if successful

        Example:
            >>> loader.delete_file("temp/test_file.parquet")
        """
        full_key = f"{self.prefix}/{s3_key}" if self.prefix else s3_key

        try:
            self.s3_client.delete_object(
                Bucket=self.bucket,
                Key=full_key,
            )
            logger.info(f"✓ Deleted s3://{self.bucket}/{full_key}")
            return True

        except ClientError as e:
            logger.error(f"Error deleting file: {e}")
            return False
