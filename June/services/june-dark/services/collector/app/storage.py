"""
Storage Manager for Collector (MinIO wrapper)
"""

import logging
from io import BytesIO
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class StorageManager:
    """MinIO storage manager for artifacts"""
    
    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = False):
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        logger.info(f"✓ Storage manager initialized: {endpoint}")
    
    def upload_data(self, bucket: str, object_name: str, data: bytes, content_type: str = "application/octet-stream"):
        """Upload data to MinIO"""
        try:
            self.client.put_object(
                bucket,
                object_name,
                BytesIO(data),
                length=len(data),
                content_type=content_type
            )
            logger.debug(f"Uploaded: {bucket}/{object_name} ({len(data)} bytes)")
        except S3Error as e:
            logger.error(f"Upload failed: {e}")
            raise
    
    def download_data(self, bucket: str, object_name: str) -> bytes:
        """Download data from MinIO"""
        try:
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Download failed: {e}")
            raise