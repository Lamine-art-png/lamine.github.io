#####################
# Locals & lookups
#####################
locals {
  tags = {
    ManagedBy = "terraform"
    Project   = var.project
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

#####################
# Networking
#####################
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project}-ecs-tasks"
  description = "Allow HTTP from anywhere to ECS tasks"
  vpc_id      = data.aws_vpc.default.id
  tags        = local.tags

  ingress {
    description = "HTTP"
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

#####################
# Logs
#####################
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 14
  tags              = local.tags
}

#####################
# ECS cluster
#####################
resource "aws_ecs_cluster" "pilot" {
  name = "${var.project}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.tags
}

#####################
# Task definition
#####################
resource "aws_ecs_task_definition" "app" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  tags                     = local.tags

  # If var.container_image is the repo **without** tag, we append :latest here.
  container_definitions = jsonencode([
    {
      name         = "api"
      image        = "${var.container_image}:latest"
      essential    = true
      portMappings = [{ containerPort = 80, protocol = "tcp" }]
      healthCheck  = {
        command     = ["CMD-SHELL", "curl -f http://localhost${var.health_check_path} || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

#####################
# ECS service
#####################
resource "aws_ecs_service" "svc" {
  name            = "${var.project}-svc"
  cluster         = aws_ecs_cluster.pilot.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"
  tags            = local.tags

  # allow replacing the single task during deploys (no extra capacity)
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets         = data.aws_subnets.default.ids
    security_groups = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  depends_on = [aws_cloudwatch_log_group.ecs]
}
