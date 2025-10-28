"""Model registry for versioned ML artifacts."""
import os
import hashlib
import joblib
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    Model artifact storage with support for filesystem, S3, and Azure backends.
    """

    def __init__(self, backend: str = "filesystem", base_path: str = "artifacts/models"):
        """
        Initialize model registry.

        Args:
            backend: Storage backend (filesystem, s3, azure)
            base_path: Base path for artifacts
        """
        self.backend = backend
        self.base_path = Path(base_path)

        if backend == "filesystem":
            self.base_path.mkdir(parents=True, exist_ok=True)

    def save_model(
        self,
        model: Any,
        model_name: str,
        version: str,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """
        Save model artifact to registry.

        Args:
            model: Model object (sklearn, etc.)
            model_name: Name of model
            version: Version string
            metadata: Optional metadata dict

        Returns:
            Dict with artifact_path, checksum, size_bytes
        """
        # Generate path
        artifact_path = self.base_path / model_name / version / "model.joblib"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        # Save model
        joblib.dump(model, artifact_path)

        # Compute checksum
        with open(artifact_path, 'rb') as f:
            artifact_bytes = f.read()
            checksum = hashlib.sha256(artifact_bytes).hexdigest()
            size_bytes = len(artifact_bytes)

        # Save metadata if provided
        if metadata:
            metadata_path = artifact_path.parent / "metadata.json"
            import json
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

        logger.info(f"Saved model: {model_name} v{version} ({size_bytes} bytes)")

        return {
            "artifact_path": str(artifact_path),
            "checksum": checksum,
            "size_bytes": str(size_bytes),
        }

    def load_model(self, model_name: str, version: str) -> Any:
        """Load model from registry."""
        artifact_path = self.base_path / model_name / version / "model.joblib"

        if not artifact_path.exists():
            raise FileNotFoundError(f"Model not found: {model_name} v{version}")

        return joblib.load(artifact_path)

    def get_latest_production(self, model_name: str, db_session) -> Optional[str]:
        """Get latest production version from database."""
        from app.models.model_run import ModelRun

        run = db_session.query(ModelRun).filter(
            ModelRun.model_name == model_name,
            ModelRun.status == "production"
        ).order_by(ModelRun.promoted_at.desc()).first()

        return run.version if run else None
