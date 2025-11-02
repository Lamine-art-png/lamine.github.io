# Use default VPC + its subnets to avoid VPC quota issues
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "in_default_vpc" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security group in the default VPC
resource "aws_security_group" "api_sg" {
  name        = "${var.project}-api-sg"
  description = "Allow HTTP from internet"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ECS cluster
module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "~> 5.12"

  cluster_name = "${var.project}-cluster"

  fargate_capacity_providers = {
    FARGATE = {
      default_capacity_provider_strategy = [{
        base   = 1
        weight = 100
      }]
    }
  }
}

# Fargate service with a single nginx container
module "api_service" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "~> 5.12"

  name                   = "${var.project}-api"
  cluster_arn            = module.ecs.cluster_arn
  desired_count          = var.desired_count
  launch_type            = "FARGATE"
  cpu                    = 256
  memory                 = 512
  assign_public_ip       = true
  enable_execute_command = true
  force_new_deployment   = true
  platform_version       = "1.4.0"

  # use two subnets from the default VPC
  subnet_ids         = slice(data.aws_subnets.in_default_vpc.ids, 0, 2)
  security_group_ids = [aws_security_group.api_sg.id]

  container_definitions = {
    api = {
      image     = "public.ecr.aws/nginx/nginx:stable"
      essential = true
      command   = ["nginx", "-g", "daemon off;"]

      port_mappings = [{
        name          = "http"
        containerPort = 80
        hostPort      = 80
        protocol      = "tcp"
      }]

      # IMPORTANT: don't let Terraform create CW log groups; let the agent do it
      create_cloudwatch_log_group = false

      log_configuration = {
        log_driver = "awslogs"
        options = {
          awslogs-group         = "/aws/ecs/${var.project}-api"
          awslogs-region        = var.region
          awslogs-stream-prefix = "api"
          awslogs-create-group  = "true"
        }
      }
    }
  }
}
