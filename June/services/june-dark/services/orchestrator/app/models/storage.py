"""
MinIO Storage Manager
"""

import logging
from typing import Optional, BinaryIO
from datetime import timedelta
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class StorageManager:
    """Manages MinIO/S3 object storage"""
    
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False
    ):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure
        self.client: Optional[Minio] = None
        self.initialized = False
    
    async def initialize(self):
        """Initialize MinIO client and create buckets"""
        try:
            logger.info(f"Initializing MinIO client at {self.endpoint}...")
            
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure
            )
            
            # Create required buckets
            buckets = [
                "june-artifacts",
                "june-screenshots",
                "june-documents",
                "june-exports"
            ]
            
            for bucket in buckets:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    logger.info(f"✓ Created bucket: {bucket}")
                else:
                    logger.info(f"✓ Bucket exists: {bucket}")
            
            self.initialized = True
            logger.info("✓ MinIO initialized successfully")
            
        except S3Error as e:
            logger.error(f"Failed to initialize MinIO: {e}")
            raise
    
    def upload_file(
        self,
        bucket: str,
        object_name: str,
        file_path: str,
        content_type: str = "application/octet-stream"
    ):
        """Upload file to MinIO"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            self.client.fput_object(
                bucket,
                object_name,
                file_path,
                content_type=content_type
            )
            logger.debug(f"Uploaded {object_name} to {bucket}")
        except S3Error as e:
            logger.error(f"Failed to upload {object_name}: {e}")
            raise
    
    def upload_data(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream"
    ):
        """Upload data directly to MinIO"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            from io import BytesIO
            self.client.put_object(
                bucket,
                object_name,
                BytesIO(data),
                length=len(data),
                content_type=content_type
            )
            logger.debug(f"Uploaded {object_name} to {bucket}")
        except S3Error as e:
            logger.error(f"Failed to upload {object_name}: {e}")
            raise
    
    def download_file(
        self,
        bucket: str,
        object_name: str,
        file_path: str
    ):
        """Download file from MinIO"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            self.client.fget_object(bucket, object_name, file_path)
            logger.debug(f"Downloaded {object_name} from {bucket}")
        except S3Error as e:
            logger.error(f"Failed to download {object_name}: {e}")
            raise
    
    def get_object(self, bucket: str, object_name: str) -> bytes:
        """Get object data from MinIO"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Failed to get {object_name}: {e}")
            raise
    
    def delete_object(self, bucket: str, object_name: str):
        """Delete object from MinIO"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            self.client.remove_object(bucket, object_name)
            logger.debug(f"Deleted {object_name} from {bucket}")
        except S3Error as e:
            logger.error(f"Failed to delete {object_name}: {e}")
            raise
    
    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = True):
        """List objects in bucket"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            objects = self.client.list_objects(
                bucket,
                prefix=prefix,
                recursive=recursive
            )
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error(f"Failed to list objects in {bucket}: {e}")
            raise
    
    def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires: timedelta = timedelta(hours=1)
    ) -> str:
        """Generate presigned URL for object"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            url = self.client.presigned_get_object(
                bucket,
                object_name,
                expires=expires
            )
            return url
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise
    
    def get_bucket_stats(self, bucket: str) -> dict:
        """Get bucket statistics"""
        if not self.initialized:
            raise RuntimeError("Storage manager not initialized")
        
        try:
            objects = list(self.client.list_objects(bucket, recursive=True))
            total_size = sum(obj.size for obj in objects)
            
            return {
                "bucket": bucket,
                "object_count": len(objects),
                "total_size_bytes": total_size,
                "total_size_gb": round(total_size / (1024**3), 2)
            }
        except S3Error as e:
            logger.error(f"Failed to get bucket stats: {e}")
            raise