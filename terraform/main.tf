locals {
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# --- Networking (default VPC/Subnets) ---
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# --- Logs ---
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 14
  tags              = local.tags
}

# --- IAM: ECS task execution role ---
data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    effect  = "Allow"
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

# --- ECS cluster ---
resource "aws_ecs_cluster" "pilot" {
  name = "${var.project}-cluster"   # e.g., agroai-manulife-pilot-cluster
  tags = local.tags
}

# --- SG for tasks (use name_prefix to avoid duplicate-name errors) ---
resource "aws_security_group" "ecs_tasks" {
  name_prefix = "${var.project}-ecs-tasks-"
  description = "Allow HTTP egress/ingress for ECS tasks"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = local.tags
}

# --- Task definition ---
# NOTE: image comes from data.aws_ecr_repository.api defined in ecr.tf
resource "aws_ecs_task_definition" "app" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  tags                     = local.tags

  container_definitions = jsonencode([
    {
      name         = "api"
      image        = "${data.aws_ecr_repository.api.repository_url}:latest"
      essential    = true
      portMappings = [{ containerPort = 80, protocol = "tcp" }]

      environment = [
        { name = "HEALTH_CHECK_PATH", value = var.health_check_path }
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://localhost$HEALTH_CHECK_PATH || exit 1"]
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

# --- ECS service (1 task, public IP) ---
resource "aws_ecs_service" "svc" {
  name            = "${var.project}-svc"
  cluster         = aws_ecs_cluster.pilot.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"
  tags            = local.tags

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = 60
  force_new_deployment              = true
  wait_for_steady_state             = true

  depends_on = [aws_cloudwatch_log_group.ecs]
}
