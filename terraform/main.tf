#############################################
# terraform/main.tf  (us-west-1 pilot, NGINX)
#############################################

# AZs
data "aws_availability_zones" "available" {
  state = "available"
}

# VPC (2 public + 2 private subnets)
module "network" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.21"

  name = "${var.project}-vpc"
  cidr = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, 2)
  private_subnets = ["10.42.1.0/24", "10.42.2.0/24"]
  public_subnets  = ["10.42.101.0/24", "10.42.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true
}

# SG: allow HTTP from anywhere
resource "aws_security_group" "api_sg" {
  name        = "${var.project}-api-sg"
  description = "Allow HTTP from internet"
  vpc_id      = module.network.vpc_id

  ingress { from_port = 80  to_port = 80  protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }
  egress  { from_port = 0   to_port = 0   protocol = "-1"  cidr_blocks = ["0.0.0.0/0"] }
}

# Logs
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api"
  retention_in_days = 14
}

# ECS cluster
module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "~> 5.12"

  cluster_name               = "${var.project}-cluster"
  fargate_capacity_providers = ["FARGATE"]
}

# ECS service (public subnets + public IP) running NGINX
module "api_service" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "~> 5.12"

  name          = "${var.project}-api"
  cluster_arn   = module.ecs.cluster_arn
  cpu           = 256
  memory        = 512
  desired_count = var.desired_count
  launch_type   = "FARGATE"

  subnet_ids           = module.network.public_subnets
  security_group_ids   = [aws_security_group.api_sg.id]
  assign_public_ip     = true
  enable_execute_command = true
  force_new_deployment   = true

  # IMPORTANT: module wants a map keyed by container name, snake_case keys
  container_definitions = {
    api = {
      image     = "public.ecr.aws/nginx/nginx:latest"
      essential = true

      port_mappings = [
        {
          name          = "http"
          containerPort = 80
          hostPort      = 80
          protocol      = "tcp"
        }
      ]

      log_configuration = {
        log_driver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  }
}
