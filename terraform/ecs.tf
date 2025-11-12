resource "aws_ecs_cluster" "api" {
  name = "agroai-manulife-pilot-cluster"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "agroai-manulife-pilot-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
     name  = "api"
     image = "${data.aws_ecr_repository.api.repository_url}:${var.image_tag}"
     # ...rest unchanged...
    }
])
}

resource "aws_ecs_service" "api" {
  name            = "agroai-manulife-pilot-svc"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  launch_type     = "FARGATE"
  desired_count   = 1

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

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }

  depends_on = [
    aws_lb_listener.api_https,
  ]
}

