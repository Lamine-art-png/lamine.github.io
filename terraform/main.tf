locals {
  tags = {
    ManagedBy = "terraform"
    Project   = var.project
  }
}

#####################
# Networking lookups
#####################
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

###########################
# Logs + IAM for ECS tasks
###########################
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 7
  tags              = local.tags
}

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

################
# ECS cluster
################
resource "aws_ecs_cluster" "pilot" {
  # Keep this stable so TF never tries to replace it
  name = "${var.project}-cluster" # agroai-manulife-pilot-cluster
  tags = local.tags
}

#########################
# Security group for ECS
#########################
resource "aws_security_group" "ecs_tasks" {
  # Use prefix so we never collide on re-creates
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

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${var.container_image}:latest" # tag added here
      essential = true
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
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])
}

################
# ECS service
################
resource "aws_ecs_service" "svc" {
  name            = "${var.project}-svc"
  cluster         = aws_ecs_cluster.pilot.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  # Safer deployments
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  force_new_deployment  = true
  wait_for_steady_state = true

  network_configuration {
    subnets         = data.aws_subnets.default.ids
    security_groups = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  tags = local.tags

  depends_on = [
    aws_cloudwatch_log_group.ecs
  ]
}
