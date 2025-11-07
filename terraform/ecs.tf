resource "aws_ecs_cluster" "api" {
  name = "agroai-manulife-pilot-cluster"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "agroai-manulife-pilot-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_image  # wired from CI/CD
      essential = true
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
      # logConfiguration, env vars, etc.
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "agroai-manulife-pilot-svc"
  cluster         = aws_ecs_cluster.api.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.ecs_api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.api_https]
}
