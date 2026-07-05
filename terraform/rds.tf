resource "aws_db_subnet_group" "api" {
  name       = "${var.project}-db-subnet"
  subnet_ids = length(var.db_subnet_ids) > 0 ? var.db_subnet_ids : var.ecs_subnet_ids

  tags = {
    Project = var.project
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.project}-rds-"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project
  }
}

resource "random_password" "db_master" {
  length           = 32
  special          = true
  override_special = "!#$%&*+-=?^_~"
}

locals {
  db_password = trimspace(var.db_password) != "" ? var.db_password : random_password.db_master.result
  managed_database_url = format(
    "postgresql://agroai:%s@%s/agroai?sslmode=require",
    urlencode(local.db_password),
    aws_db_instance.api.endpoint,
  )
  runtime_database_url = trimspace(var.database_url) != "" ? var.database_url : local.managed_database_url
}

resource "aws_db_instance" "api" {
  identifier = "${var.project}-db"

  engine         = "postgres"
  engine_version = "15"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "agroai"
  username = "agroai"
  password = local.db_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.api.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible    = false
  multi_az               = var.db_multi_az
  deletion_protection    = var.db_deletion_protection
  skip_final_snapshot    = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${var.project}-db-final"

  backup_retention_period = 7
  backup_window           = "07:00-08:00"
  maintenance_window      = "sun:09:00-sun:10:00"

  auto_minor_version_upgrade      = true
  copy_tags_to_snapshot           = true
  performance_insights_enabled    = true
  performance_insights_retention_period = 7

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
    DataClass = "customer-operational-records"
  }
}

output "rds_endpoint" {
  value       = aws_db_instance.api.endpoint
  description = "RDS PostgreSQL endpoint"
}

output "database_url" {
  value       = local.runtime_database_url
  description = "PostgreSQL connection string used by the runtime."
  sensitive   = true
}
