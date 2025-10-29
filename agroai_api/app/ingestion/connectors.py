"""Data source connectors for file-drop, S3, and Azure Blob."""
import os
import hashlib
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DataConnector(ABC):
    """Base class for data source connectors."""

    @abstractmethod
    def list_files(self, path: str) -> List[str]:
        """List available files at path."""
        pass

    @abstractmethod
    def read_file(self, uri: str) -> bytes:
        """Read file contents."""
        pass

    @abstractmethod
    def compute_checksum(self, uri: str) -> str:
        """Compute SHA-256 checksum of file."""
        pass


class FileSystemConnector(DataConnector):
    """Local filesystem connector for file-drop directories."""

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def list_files(self, path: str = "") -> List[str]:
        """List files in directory."""
        search_path = self.base_path / path if path else self.base_path
        return [str(f.relative_to(self.base_path)) for f in search_path.glob("**/*") if f.is_file()]

    def read_file(self, uri: str) -> bytes:
        """Read file contents."""
        file_path = self.base_path / uri
        with open(file_path, 'rb') as f:
            return f.read()

    def compute_checksum(self, uri: str) -> str:
        """Compute SHA-256 checksum."""
        file_path = self.base_path / uri
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)
        return sha256.hexdigest()


class S3Connector(DataConnector):
    """AWS S3 connector for cloud storage."""

    def __init__(self, bucket: str, prefix: str = ""):
        try:
            import boto3
            self.s3_client = boto3.client('s3')
            self.bucket = bucket
            self.prefix = prefix
        except ImportError:
            raise ImportError("boto3 required for S3 connector. Install with: pip install boto3")

    def list_files(self, path: str = "") -> List[str]:
        """List objects in S3 bucket."""
        full_prefix = f"{self.prefix}/{path}" if path else self.prefix
        response = self.s3_client.list_objects_v2(Bucket=self.bucket, Prefix=full_prefix)
        return [obj['Key'] for obj in response.get('Contents', [])]

    def read_file(self, uri: str) -> bytes:
        """Read S3 object."""
        response = self.s3_client.get_object(Bucket=self.bucket, Key=uri)
        return response['Body'].read()

    def compute_checksum(self, uri: str) -> str:
        """Compute checksum (use ETag if available)."""
        response = self.s3_client.head_object(Bucket=self.bucket, Key=uri)
        # ETag is often MD5, but for multipart uploads it's different
        # For consistency, compute SHA-256 ourselves
        content = self.read_file(uri)
        return hashlib.sha256(content).hexdigest()


class AzureBlobConnector(DataConnector):
    """Azure Blob Storage connector."""

    def __init__(self, connection_string: str, container: str, prefix: str = ""):
        try:
            from azure.storage.blob import BlobServiceClient
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            self.container_client = self.blob_service_client.get_container_client(container)
            self.prefix = prefix
        except ImportError:
            raise ImportError("azure-storage-blob required. Install with: pip install azure-storage-blob")

    def list_files(self, path: str = "") -> List[str]:
        """List blobs in container."""
        full_prefix = f"{self.prefix}/{path}" if path else self.prefix
        return [blob.name for blob in self.container_client.list_blobs(name_starts_with=full_prefix)]

    def read_file(self, uri: str) -> bytes:
        """Read blob content."""
        blob_client = self.container_client.get_blob_client(uri)
        return blob_client.download_blob().readall()

    def compute_checksum(self, uri: str) -> str:
        """Compute SHA-256 checksum."""
        content = self.read_file(uri)
        return hashlib.sha256(content).hexdigest()


def get_connector(source_type: str, **kwargs) -> DataConnector:
    """Factory to get appropriate connector."""
    connectors = {
        "file": FileSystemConnector,
        "s3": S3Connector,
        "azure": AzureBlobConnector,
    }

    connector_class = connectors.get(source_type)
    if not connector_class:
        raise ValueError(f"Unknown connector type: {source_type}")

    return connector_class(**kwargs)
