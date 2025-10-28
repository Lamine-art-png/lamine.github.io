"""Model run registry for ML model lifecycle management."""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON, Boolean, Text
from datetime import datetime
from app.db.base import Base


class ModelRun(Base):
    """Track ML model training runs, metrics, and promotion status."""

    __tablename__ = "model_runs"

    id = Column(String, primary_key=True, index=True)

    # Model metadata
    model_name = Column(String, nullable=False, index=True)  # e.g., "irrigation_recommender"
    version = Column(String, nullable=False, index=True)  # e.g., "rf-ens-1.0.0"
    algorithm = Column(String, nullable=False)  # e.g., "random_forest", "gradient_boosting"

    # Dataset information
    dataset_hash = Column(String, nullable=False, index=True)  # SHA-256 of training data
    dataset_size = Column(String, default="0")  # Number of training samples
    train_start_date = Column(DateTime, nullable=True)
    train_end_date = Column(DateTime, nullable=True)

    # Segmentation
    crop_type = Column(String, nullable=True, index=True)  # Crop-specific model
    region = Column(String, nullable=True, index=True)  # Geographic region
    season = Column(String, nullable=True)  # Growing season

    # Hyperparameters
    hyperparameters = Column(JSON, nullable=False)  # Full hyperparameter dict

    # Metrics
    mae = Column(Float, nullable=True)  # Mean Absolute Error
    rmse = Column(Float, nullable=True)  # Root Mean Squared Error
    r2_score = Column(Float, nullable=True)  # R² Score
    metrics_json = Column(JSON, nullable=True)  # Additional metrics

    # Feature importance
    feature_importances = Column(JSON, nullable=True)  # Top features with scores

    # Artifact storage
    artifact_backend = Column(String, nullable=False)  # filesystem | s3 | azure
    artifact_path = Column(String, nullable=False)  # Full path to model artifact
    artifact_checksum = Column(String, nullable=True)  # SHA-256 of artifact
    artifact_size_bytes = Column(String, nullable=True)

    # Promotion status
    status = Column(String, default="training", nullable=False, index=True)  # training | pilot | production | archived
    promoted_at = Column(DateTime, nullable=True, index=True)
    promoted_by = Column(String, nullable=True)

    # Lifecycle
    training_started_at = Column(DateTime, default=datetime.utcnow, index=True)
    training_completed_at = Column(DateTime, nullable=True)
    training_duration_seconds = Column(String, nullable=True)

    # Audit
    created_by = Column(String, nullable=True)  # System user who triggered training
    notes = Column(Text, nullable=True)  # Human-readable notes

    __table_args__ = (
        Index('ix_modelrun_status_name', 'status', 'model_name'),
        Index('ix_modelrun_crop_region', 'crop_type', 'region'),
        Index('ix_modelrun_version', 'model_name', 'version'),
    )
