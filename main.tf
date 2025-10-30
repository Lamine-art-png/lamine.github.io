#############################################
# terraform/main.tf  (us-west-1 deployment)
#############################################

# Availability Zones (N. California uses e.g., a/c)
data "aws_availability_zones" "available" {
  state = "available"
}

# --- Networking (VPC/Subnets/SGs) — simplified for pilot ---
module "network" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.project}-vpc"
  cidr = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, 2)
  private_subnets = ["10.42.1.0/24", "10.42.2.0/24"]
  public_subnets  = ["10.42.101.0/24", "10.42.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags  = { "kubernetes.io/role/elb"         = "1" }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }
}

resource "aws_security_group" "api_sg" {
  name        = "${var.project}-api-sg"
  description = "Allow HTTP from internet"
  vpc_id      = module.network.vpc_id

  ingress { from_port = 80 to_port = 80 protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }
  egress  { from_port = 0  to_port = 0  protocol = "-1"  cidr_blocks = ["0.0.0.0/0"] }
}

# --- RDS Postgres for pilot ---
module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.5"

  identifier                = "${var.project}-pg"
  engine                    = "postgres"
  engine_version            = "16.2"
  instance_class            = var.db_instance
  username                  = var.db_username
  db_name                   = var.db_name
  create_random_password    = true
  allocated_storage         = 20
  deletion_protection       = false
  publicly_accessible       = false
  backup_window             = "05:00-06:00"
  maintenance_window        = "sun:06:00-sun:07:00"
  performance_insights_enabled = true
  monitoring_interval       = 60

  vpc_security_group_ids = [aws_security_group.api_sg.id]
  subnet_ids             = module.network.private_subnets
}

# --- ECR repo for API image (ONLY ONE DEFINITION) ---
resource "aws_ecr_repository" "api" {
  name = "${var.project}-api"   # e.g., agroai-manulife-pilot-api
  image_scanning_configuration { scan_on_push = true }
  force_delete = true
}

# --- Secrets Manager for DB URL ---
resource "aws_secretsmanager_secret" "db_url" {
  name = "${var.project}/db_url"
}

resource "aws_secretsmanager_secret_version" "db_url_v" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = jsonencode({
    url = "postgresql://${module.db.db_instance_username}:${module.db.db_instance_password}@${module.db.db_instance_address}:5432/${module.db.db_instance_name}"
  })
}

# --- S3 buckets for raw data and models ---
resource "aws_s3_bucket" "raw" {
  bucket        = "${var.project}-raw-${var.env}"
  force_destroy = true
}

resource "aws_s3_bucket" "models" {
  bucket        = "${var.project}-models-${var.env}"
  force_destroy = true
}

# --- CloudWatch Log Group used by ECS service ---
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api"
  retention_in_days = 14
}

# --- ECS Fargate Cluster + Service for API ---
module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "~> 5.11"

  cluster_name               = "${var.project}-cluster"
  fargate_capacity_providers = ["FARGATE"]
}

module "api_service" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "~> 5.11"

  name          = "${var.project}-api"
  cluster_arn   = module.ecs.cluster_arn
  cpu           = 256
  memory        = 512
  desired_count = var.desired_count
  launch_type   = "FARGATE"

  # expose pilot quickly (no ALB yet)
  subnet_ids         = module.network.public_subnets   # <-- was private_subnets
  security_group_ids = [aws_security_group.api_sg.id]
  assign_public_ip   = true                            # <-- was false
  force_new_deployment = true                         # ensure tasks roll after net change

  container_definitions = [
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:${var.api_image}"
      essential = true
      portMappings = [{ containerPort = 80, hostPort = 80 }]
      environment = [
        { name = "ENV", value = var.env },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.db_url.arn },
      ]
      logConfiguration = {
        logDriver = "awslogs",
        options = {
          awslogs-group         = "/ecs/${var.project}-api"
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ]
}

  subnet_ids         = module.network.private_subnets
  security_group_ids = [aws_security_group.api_sg.id]
  assign_public_ip   = false

  enable_execute_command = true
}

