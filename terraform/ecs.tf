resource "aws_ecs_cluster" "api" {
  name = "${var.project}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Project = var.project
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}/api"
  retention_in_days = 14

  tags = {
    Project = var.project
  }
}

resource "aws_cloudwatch_log_group" "connector_worker" {
  name              = "/ecs/${var.project}/connector-worker"
  retention_in_days = 14

  tags = {
    Project = var.project
  }
}

data "aws_region" "current" {}

locals {
  base_runtime_environment = {
    APP_ENV                                = "production"
    ENABLE_SCHEDULER                       = "false"
    ENABLE_METRICS                         = "true"
    SYNC_INTERVAL_MINUTES                  = tostring(var.sync_interval_minutes)
    TASK_QUEUE_BACKEND                     = trimspace(local.runtime_redis_url) != "" ? "redis_streams" : "disabled"
    TASK_QUEUE_STREAM                      = var.task_queue_stream
    TASK_QUEUE_GROUP                       = var.task_queue_group
    TASK_QUEUE_STREAM_MAXLEN               = tostring(var.task_queue_stream_maxlen)
    TASK_QUEUE_LEASE_SECONDS               = tostring(var.task_queue_lease_seconds)
    TASK_QUEUE_MAX_ATTEMPTS                = tostring(var.task_queue_max_attempts)
    CONNECTOR_OBJECT_STORAGE_BACKEND       = local.runtime_object_backend
    CONNECTOR_OBJECT_BUCKET                = local.runtime_object_bucket
    CONNECTOR_OBJECT_PREFIX                = var.connector_object_prefix
    CONNECTOR_OBJECT_REGION                = local.runtime_object_region
    CONNECTOR_OBJECT_ENDPOINT_URL          = local.runtime_object_endpoint
    CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION = var.connector_credential_active_key_version
  }

  runtime_environment = merge(local.base_runtime_environment, var.ecs_runtime_environment)
  runtime_environment_list = [
    for name, value in local.runtime_environment : {
      name  = name
      value = value
    }
  ]
  runtime_secret_list = [
    for name, value_from in var.ecs_runtime_secrets : {
      name      = name
      valueFrom = value_from
    }
  ]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name         = "api"
      image        = "${data.aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential    = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment      = concat(local.runtime_environment_list, [{ name = "PORT", value = "8000" }])
      secrets          = local.runtime_secret_list
      logConfiguration = {
        logDriver = "awslogs"
        options   = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "api"
        }
      }
      healthCheck = {
        command = [
          "CMD-SHELL",
          "curl -f http://localhost:8000/v1/health || exit 1"
        ]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
      stopTimeout = 30
    }
  ])

  tags = {
    Project   = var.project
    Component = "api"
  }
}

resource "aws_ecs_task_definition" "connector_worker" {
  family                   = "${var.project}-connector-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name             = "connector-worker"
      image            = "${data.aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential        = true
      command          = ["python", "-m", "app.workers.connector_worker"]
      environment      = local.runtime_environment_list
      secrets          = local.runtime_secret_list
      logConfiguration = {
        logDriver = "awslogs"
        options   = {
          awslogs-group         = aws_cloudwatch_log_group.connector_worker.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "worker"
        }
      }
      stopTimeout = 120
    }
  ])

  tags = {
    Project   = var.project
    Component = "connector-worker"
  }
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-api"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  enable_execute_command             = true

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
    Component = "api"
  }
}

resource "aws_ecs_service" "connector_worker" {
  name            = "${var.project}-connector-worker"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.connector_worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  enable_execute_command             = true

  network_configuration {
    subnets          = var.ecs_subnet_ids
    security_groups  = [aws_security_group.ecs_api.id]
    assign_public_ip = true
  }

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
    Component = "connector-worker"
  }
}
