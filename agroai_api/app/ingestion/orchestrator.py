"""Batch ingestion orchestrator for scheduled data processing."""
import uuid
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy.orm import Session

from app.ingestion.connectors import get_connector
from app.models.ingestion_run import IngestionRun
from app.models.telemetry import Telemetry
from app.schemas.telemetry import TelemetryType

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """Orchestrate batch ingestion from multiple sources."""

    def __init__(self, db: Session):
        self.db = db

    def ingest_batch(
        self,
        tenant_id: str,
        field_id: Optional[str],
        source_type: str,
        source_uri: str,
        data_type: str,
        connector_kwargs: Optional[Dict] = None,
        batch_id: Optional[str] = None,
        triggered_by: str = "manual",
    ) -> IngestionRun:
        """
        Ingest a batch of data from a source.

        Args:
            tenant_id: Tenant ID
            field_id: Optional field ID
            source_type: Type of source (file, s3, azure)
            source_uri: URI/path to data file
            data_type: Type of data (telemetry, weather, soil, flow)
            connector_kwargs: Additional kwargs for connector initialization
            batch_id: Optional batch ID to group related ingestions
            triggered_by: How ingestion was triggered

        Returns:
            IngestionRun record
        """
        # Create ingestion run record
        run_id = str(uuid.uuid4())
        batch_id = batch_id or str(uuid.uuid4())

        run = IngestionRun(
            id=run_id,
            tenant_id=tenant_id,
            field_id=field_id,
            source_type=source_type,
            source_uri=source_uri,
            status="pending",
            data_type=data_type,
            batch_id=batch_id,
            triggered_by=triggered_by,
            started_at=datetime.utcnow(),
        )

        self.db.add(run)
        self.db.commit()

        try:
            # Get connector
            connector = get_connector(source_type, **(connector_kwargs or {}))

            # Compute checksum
            run.source_checksum = connector.compute_checksum(source_uri)

            # Read and parse data
            run.status = "processing"
            self.db.commit()

            data = connector.read_file(source_uri)

            # Transform and load (simplified - production would parse CSV/JSON)
            rows_accepted, rows_rejected = self._process_data(
                tenant_id=tenant_id,
                field_id=field_id,
                data=data,
                data_type=data_type,
            )

            # Update run
            run.rows_total = rows_accepted + rows_rejected
            run.rows_accepted = rows_accepted
            run.rows_rejected = rows_rejected
            run.status = "success"
            run.completed_at = datetime.utcnow()
            run.duration_seconds = int((run.completed_at - run.started_at).total_seconds())

            self.db.commit()

            logger.info(
                f"Ingestion successful: {run_id}",
                extra={
                    "tenant_id": tenant_id,
                    "field_id": field_id,
                    "rows_accepted": rows_accepted,
                    "duration_seconds": run.duration_seconds,
                }
            )

        except Exception as e:
            logger.error(f"Ingestion failed: {run_id}", exc_info=True)

            run.status = "failed"
            run.error_message = str(e)
            run.error_details = json.dumps({"exception_type": type(e).__name__})
            run.completed_at = datetime.utcnow()
            run.duration_seconds = int((run.completed_at - run.started_at).total_seconds())

            self.db.commit()

        return run

    def _process_data(
        self,
        tenant_id: str,
        field_id: Optional[str],
        data: bytes,
        data_type: str,
    ) -> tuple:
        """
        Process and load data into database.

        Returns:
            Tuple of (rows_accepted, rows_rejected)
        """
        # Simplified processing - production would parse CSV/JSON properly
        # For now, mock successful ingestion
        rows_accepted = 1
        rows_rejected = 0

        return rows_accepted, rows_rejected
