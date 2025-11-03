# --- Use existing default VPC and its subnets ---
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security group for ECS tasks (allow HTTP in; all egress)
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project}-ecs-tasks-sg"
  description = "Allow HTTP to ECS tasks"
  vpc_id      = data.aws_vpc.default.id

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

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# CloudWatch logs for the task
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 14
}

# ECS cluster
resource "aws_ecs_cluster" "pilot" {
  name = "${var.project}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# IAM role for ECS task execution (pull image, write logs)
data "aws_iam_policy_document" "ecs_task_exec_assume" {
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
  assume_role_policy = data.aws_iam_policy_document.ecs_task_exec_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_exec" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Minimal nginx task definition (Fargate)
resource "aws_ecs_task_definition" "nginx" {
  family                   = "${var.project}-nginx"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "nginx"
      image     = "public.ecr.aws/nginx/nginx:stable-alpine"
      essential = true
      portMappings = [
        {
          containerPort = 80
          hostPort      = 80
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "nginx"
        }
      }
    }
  ])
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# ECS service in default VPC public subnets, with public IP
resource "aws_ecs_service" "nginx" {
  name            = "${var.project}-svc"
  cluster         = aws_ecs_cluster.pilot.id
  task_definition = aws_ecs_task_definition.nginx.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = slice(data.aws_subnets.default.ids, 0, 2)
    assign_public_ip = true
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  depends_on = [
    aws_iam_role_policy_attachment.ecs_exec,
    aws_cloudwatch_log_group.ecs
  ]

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# Helpful outputs
output "default_vpc_id" {
  value = data.aws_vpc.default.id
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.pilot.name
}

output "ecs_service_name" {
  value = aws_ecs_service.nginx.name
}

output "subnet_ids_used" {
  value = slice(data.aws_subnets.default.ids, 0, 2)
}
