################################
# Common tags
################################

locals {
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

################################
# Network data
################################

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

################################
# CloudWatch Logs
################################

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 14
  tags              = local.tags
}

################################
# IAM: ECS task execution role
################################

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project}-ecs-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "ecs_exec_basic" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

################################
# ECS Cluster
################################

resource "aws_ecs_cluster" "pilot" {
  name = "${var.project}-cluster"
  tags = local.tags
}

################################
# Security Group for tasks
################################

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project}-ecs-tasks"
  description = "Allow inbound HTTP to API tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = var.container_port
    to_port     = var.container_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

################################
# Task Definition
################################

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.project}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_image != "" ? var.api_image : "${data.aws_ecr_repository.api.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "PORT",              value = tostring(var.container_port) },
        { name = "HEALTH_CHECK_PATH", value = var.health_check_path },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }

      # TEMP: super-safe health check to prove the task can stay up
      # Once it's stable, we'll point this at your real endpoint.
      healthCheck = {
        command     = ["CMD-SHELL", "echo healthy"]
        interval    = 30
        retries     = 3
        timeout     = 5
        startPeriod = 5
      }
    }
  ])

  tags = local.tags
}

################################
# ECS Service (no ALB yet)
################################

resource "aws_ecs_service" "svc" {
  name            = "${var.project}-svc"
  cluster         = aws_ecs_cluster.pilot.arn
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = data.aws_subnets.default.ids
    security_groups = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  tags = local.tags
}
