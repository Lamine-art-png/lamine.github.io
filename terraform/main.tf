#############################################
# ECS on Fargate in the *default VPC*
# - No new VPC/NAT/IGW (avoids VPCLimitExceeded)
# - Container creates its own CloudWatch Logs group
#############################################

# Use the region’s default VPC and its subnets
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default_vpc_subnets" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security Group (HTTP open; unrestricted egress)
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

# ECS Cluster (Fargate)
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

# One-container service (nginx for a clean health check)
module "api_service" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "~> 5.12"

  name                   = "${var.project}-api"
  cluster_arn            = module.ecs.cluster_arn
  desired_count          = var.desired_count
  launch_type            = "FARGATE"
  cpu                    = 256
  memory                 = 512
  platform_version       = "1.4.0"
  assign_public_ip       = true
  enable_execute_command = true
  force_new_deployment   = true

  subnet_ids         = data.aws_subnets.default_vpc_subnets.ids
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

      log_configuration = {
        log_driver = "awslogs"
        options = {
          # Let the task create it on first run — avoids “already exists” in TF
          awslogs-group         = "/aws/ecs/${var.project}-api"
          awslogs-region        = var.region
          awslogs-stream-prefix = "api"
          awslogs-create-group  = "true"
        }
      }
    }
  }
}
