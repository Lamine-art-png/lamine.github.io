#############################################
# terraform/main.tf  (us-west-1 pilot)
#############################################

data "aws_availability_zones" "available" {
  state = "available"
}

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

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api"
  retention_in_days = 14
}

module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "~> 5.11"

  cluster_name               = "${var.project}-cluster"
  fargate_capacity_providers = ["FARGATE"]
}

module "api_service" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "~> 5.11"

  name            = "${var.project}-api"
  cluster_arn     = module.ecs.cluster_arn
  cpu             = 256
  memory          = 512
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  subnet_ids         = module.network.public_subnets
  security_group_ids = [aws_security_group.api_sg.id]
  assign_public_ip   = true
  force_new_deployment = true

  container_definitions = [
    {
      name      = "api"
      image     = "public.ecr.aws/nginx/nginx:latest"
      essential = true
      portMappings = [{ containerPort = 80, hostPort = 80 }]
      logConfiguration = {
        logDriver = "awslogs",
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ]
}
