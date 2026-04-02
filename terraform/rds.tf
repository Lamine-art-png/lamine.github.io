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

resource "aws_db_instance" "api" {
  identifier = "${var.project}-db"

  engine         = "postgres"
  engine_version = "15"
  instance_class = "db.t3.micro"

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"

  db_name  = "agroai"
  username = "agroai"
  password = "change-me-in-production"  # Use AWS Secrets Manager in production

  db_subnet_group_name   = aws_db_subnet_group.api.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  skip_final_snapshot = true
  publicly_accessible = false

  backup_retention_period = 7
  multi_az                = false  # Set true for production HA

  tags = {
    Project = var.project
  }
}

output "rds_endpoint" {
  value       = aws_db_instance.api.endpoint
  description = "RDS PostgreSQL endpoint"
}

output "database_url" {
  value       = "postgresql://agroai:change-me-in-production@${aws_db_instance.api.endpoint}/agroai"
  description = "Full database connection string"
  sensitive   = true
}
