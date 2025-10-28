"""CLI tools for model management and tenant operations."""
import click
from rich.console import Console
from rich.table import Table
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import SessionLocal
from app.services.api_key_service import APIKeyService
from app.models.model_run import ModelRun

console = Console()


@click.group()
def cli():
    """AGRO-AI CLI for enterprise operations."""
    pass


@cli.group()
def apikey():
    """Manage API keys."""
    pass


@apikey.command("create")
@click.option("--tenant-id", required=True, help="Tenant ID")
@click.option("--name", required=True, help="Key name")
@click.option("--role", default="analyst", help="Role (owner/analyst/viewer)")
@click.option("--expires-days", type=int, help="Expiration in days")
def create_apikey(tenant_id, name, role, expires_days):
    """Create a new API key."""
    db = SessionLocal()

    try:
        api_key, full_key = APIKeyService.create_api_key(
            db=db,
            tenant_id=tenant_id,
            name=name,
            role=role,
            expires_days=expires_days,
        )

        console.print(f"[green]✓ API Key created successfully[/green]")
        console.print(f"\n[bold]Key ID:[/bold] {api_key.id}")
        console.print(f"[bold]Key Prefix:[/bold] {api_key.key_prefix}")
        console.print(f"\n[yellow]⚠ SAVE THIS KEY - IT WON'T BE SHOWN AGAIN:[/yellow]")
        console.print(f"[bold cyan]{full_key}[/bold cyan]\n")

    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    finally:
        db.close()


@apikey.command("list")
@click.option("--tenant-id", required=True, help="Tenant ID")
def list_apikeys(tenant_id):
    """List API keys for a tenant."""
    db = SessionLocal()

    try:
        keys = APIKeyService.list_api_keys(db=db, tenant_id=tenant_id, active_only=False)

        table = Table(title=f"API Keys for Tenant: {tenant_id}")
        table.add_column("Prefix", style="cyan")
        table.add_column("Name")
        table.add_column("Role")
        table.add_column("Active", style="green")
        table.add_column("Created")

        for key in keys:
            table.add_row(
                key.key_prefix,
                key.name,
                key.role,
                "✓" if key.active else "✗",
                key.created_at.strftime("%Y-%m-%d"),
            )

        console.print(table)

    finally:
        db.close()


@cli.group()
def model():
    """Manage ML models."""
    pass


@model.command("promote")
@click.option("--model-id", required=True, help="Model run ID")
@click.option("--status", required=True, type=click.Choice(["pilot", "production"]))
@click.option("--promoted-by", help="Who is promoting")
def promote_model(model_id, status, promoted_by):
    """Promote a model to pilot or production."""
    db = SessionLocal()

    try:
        model_run = db.query(ModelRun).filter(ModelRun.id == model_id).first()

        if not model_run:
            console.print(f"[red]✗ Model {model_id} not found[/red]")
            return

        from datetime import datetime
        model_run.status = status
        model_run.promoted_at = datetime.utcnow()
        model_run.promoted_by = promoted_by

        db.commit()

        console.print(f"[green]✓ Model {model_run.model_name} v{model_run.version} promoted to {status}[/green]")

    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
    finally:
        db.close()


@model.command("list")
@click.option("--model-name", help="Filter by model name")
@click.option("--status", help="Filter by status")
def list_models(model_name, status):
    """List model runs."""
    db = SessionLocal()

    try:
        query = db.query(ModelRun)

        if model_name:
            query = query.filter(ModelRun.model_name == model_name)
        if status:
            query = query.filter(ModelRun.status == status)

        models = query.order_by(ModelRun.training_started_at.desc()).limit(20).all()

        table = Table(title="Model Runs")
        table.add_column("Model", style="cyan")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("MAE")
        table.add_column("R²")
        table.add_column("Trained")

        for m in models:
            table.add_row(
                m.model_name,
                m.version,
                m.status,
                f"{m.mae:.3f}" if m.mae else "N/A",
                f"{m.r2_score:.3f}" if m.r2_score else "N/A",
                m.training_started_at.strftime("%Y-%m-%d"),
            )

        console.print(table)

    finally:
        db.close()


if __name__ == "__main__":
    cli()
