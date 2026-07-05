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

data "aws_region" "current" {}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      "name" : "api",
      "image" : "${data.aws_ecr_repository.api.repository_url}:${var.image_tag}",
      "essential" : true,
      "portMappings" : [
        {
          "containerPort" : 8000,
          "hostPort" : 8000,
          "protocol" : "tcp"
        }
      ],
      "environment" : [
        {
          "name" : "PORT",
          "value" : "8000"
        },
        {
          "name" : "OPENWEATHER_API_KEY",
          "value" : var.openweather_api_key
        },
        {
          "name" : "DATABASE_URL",
          "value" : var.database_url
        },
        {
          "name" : "SECRET_KEY",
          "value" : var.secret_key
        },
        {
          "name" : "WISECONN_API_KEY",
          "value" : var.wiseconn_api_key
        },
        {
          "name" : "ENABLE_SCHEDULER",
          "value" : "true"
        },
        {
          "name" : "SYNC_INTERVAL_MINUTES",
          "value" : tostring(var.sync_interval_minutes)
        },
        {
          "name" : "ENABLE_METRICS",
          "value" : "true"
        }
      ],
      "logConfiguration" : {
        "logDriver" : "awslogs",
        "options" : {
          "awslogs-group" : aws_cloudwatch_log_group.api.name,
          "awslogs-region" : data.aws_region.current.name,
          "awslogs-stream-prefix" : "api"
        }
      },
      "healthCheck" : {
        "command" : [
          "CMD-SHELL",
          "curl -f http://localhost:8000/v1/health || exit 1"
        ],
        "interval" : 30,
        "timeout" : 5,
        "retries" : 3,
        "startPeriod" : 10
      }
    }
  ])

  tags = {
    Project = var.project
  }
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-svc"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.ecs_subnet_ids
    security_groups  = [aws_security_group.ecs_api.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.api_container_port
  }

  depends_on = [
    aws_lb_target_group.api,
    aws_lb_listener.api_http,
    aws_lb_listener.api_https
  ]

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

