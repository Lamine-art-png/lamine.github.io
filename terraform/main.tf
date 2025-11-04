############################################
# ECS Fargate service on default VPC (HTTP)
############################################

locals {
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# Use the default VPC and its subnets (public by default)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

#############################
# Networking: SG for the app
#############################
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project}-ecs-sg"
  description = "Allow HTTP to ECS tasks"
  vpc_id      = data.aws_vpc.default.id
  tags        = local.tags

  egress {
    description = "all egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

#####################
# Logs (CloudWatch)
#####################
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 7
  tags              = local.tags
}

#####################
# IAM (execution role)
#####################
data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project}-ecs-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = local.tags
}

# Standard execution role policy (pull from ECR, write logs, etc.)
resource "aws_iam_role_policy_attachment" "ecs_exec_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

#####################
# ECS cluster
#####################
resource "aws_ecs_cluster" "pilot" {
  name = "${var.project}-cluster"
  tags = local.tags

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

#####################
# Task definition
#####################
resource "aws_ecs_task_definition" "app" {
  family                   = "${var.project}-app"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  tags                     = local.tags

  container_definitions = jsonencode([
    {
      name         = "api"
      image        = var.container_image  # e.g. 2920....dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api:latest
      essential    = true
      portMappings = [
        { containerPort = 80, protocol = "tcp" }
      ]
      healthCheck = {
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

  network_configuration {
    subnets         = data.aws_subnets.default.ids
    security_groups = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  # Ensure the log group exists before first run
  depends_on = [
    aws_cloudwatch_log_group.ecs
  ]
}
