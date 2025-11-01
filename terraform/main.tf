#############################################
# terraform/main.tf  (us-west-1 pilot)
# - VPC (2 public + 2 private subnets)
# - SG allowing HTTP
# - CloudWatch log group
# - ECS cluster + Fargate service
# - Public IP on tasks, image = public NGINX
#############################################

# Availability Zones
data "aws_availability_zones" "available" {
  state = "available"
}

# --- Networking (VPC/Subnets) ---
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
}

# --- Security Group (allow HTTP from Internet) ---
resource "aws_security_group" "api_sg" {
  name        = "${var.project}-api-sg"
  description = "Allow HTTP from internet"
  vpc_id      = module.network.vpc_id

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

# --- CloudWatch Log Group for ECS ---
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api"
  retention_in_days = 14
}

# --- ECS Cluster ---
module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "~> 5.11"

  cluster_name               = "${var.project}-cluster"
  fargate_capacity_providers = ["FARGATE"]
}

# --- ECS Fargate Service (public, no ALB) ---
module "api_service" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "~> 5.11"

  name          = "${var.project}-api"
  cluster_arn   = module.ecs.cluster_arn
  cpu           = 256
  memory        = 512
  desired_count = var.desired_count
  launch_type   = "FARGATE"

  # Fast pilot: run in public subnets with a public IP
  subnet_ids         = module.network.public_subnets
  security_group_ids = [aws_security_group.api_sg.id]
  assign_public_ip   = true
  force_new_deployment = true
  enable_execute_command = true

  # Use a public image so we don't depend on ECR yet
  container_definitions = [
    {
      name      = "api"
      image     = "public.ecr.aws/nginx/nginx:latest"
      essential = true

      portMappings = [
        { containerPort = 80, hostPort = 80 }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ]

  depends_on = [aws_cloudwatch_log_group.api]
}
