###########################
# ECS Cluster & logging
###########################

resource "aws_ecs_cluster" "api" {
  name = "${var.project}-cluster"

  tags = {
    Project = var.project
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}"
  retention_in_days = 14

  tags = {
    Project = var.project
  }
}

# Discover the active AWS region for the log driver
data "aws_region" "current" {}

# OpenWeather API key from SSM Parameter Store
data "aws_ssm_parameter" "openweather_api_key" {
  name = "/agroai/api/openweather_api_key"
}

###########################
# Task definition (Fargate)
###########################

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  # Image comes from ECR (declared in ecr.tf as data.aws_ecr_repository.api)
  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${data.aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "PORT"
          value = "8000"
        }
      ]

      secrets = [
        {
          name      = "OPENWEATHER_API_KEY"
          valueFrom = data.aws_ssm_parameter.openweather_api_key.arn
        }
      ]

      # CloudWatch Logs configuration
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "api"
        }
      }

      # Container health check (matches FastAPI /v1/health)
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/v1/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
    }
  ])

  tags = {
    Project = var.project
  }
}

###########################
# ECS Service (targets ALB)
###########################

resource "aws_ecs_service" "api" {
  name            = "${var.project}-svc"
  cluster         = aws_ecs_cluster.api.arn
  task_definition = aws_ecs_task_definition.api.arn
  launch_type     = "FARGATE"

  desired_count = 1

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.ecs_api.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  tags = {
    Project = var.project
  }

  depends_on = [
    aws_lb_listener.api_https
  ]
}

