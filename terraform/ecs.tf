############################
# ECS cluster
############################

# Existing cluster (imported or created by TF)
resource "aws_ecs_cluster" "api" {
  name = "agroai-manulife-pilot-cluster"
}

############################
# Task execution IAM role
############################

resource "aws_iam_role" "ecs_task_execution" {
  name = "ecsTaskExecutionRole-agroai-manulife-pilot"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

############################
# Task definition
############################

resource "aws_ecs_task_definition" "api" {
  family                   = "agroai-manulife-pilot-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api:latest"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      # add environment / logging blocks here if you need them
    }
  ])
}

############################
# ECS service behind ALB
############################

resource "aws_ecs_service" "api" {
  name            = "agroai-manulife-pilot-svc"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    # This must be subnets in vpc-0c4cf14e0f5f0f680
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener.api_http,
    aws_lb_listener.api_https,
  ]
}
