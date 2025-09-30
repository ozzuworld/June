"""
Storage manager for Enricher
"""

import logging
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class StorageManager:
    """MinIO storage manager"""
    
    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = False):
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
    
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