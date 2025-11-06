locals {
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# ALB security group (only when create_alb = true)
resource "aws_security_group" "alb" {
  count       = var.create_alb ? 1 : 0
  name        = "${var.project}-alb"
  description = "ALB security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
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

  tags = local.tags
}

# ALB itself (optional)
resource "aws_lb" "api" {
  count                      = var.create_alb ? 1 : 0
  name                       = "${var.project}-alb"
  load_balancer_type         = "application"
  subnets                    = data.aws_subnets.default.ids
  security_groups            = [aws_security_group.alb[0].id]
  enable_deletion_protection = false

  tags = local.tags
}

# Target group (optional)
resource "aws_lb_target_group" "api" {
  count       = var.create_alb ? 1 : 0
  name        = "${var.project}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = data.aws_vpc.default.id

  health_check {
    enabled             = true
    path                = var.health_check_path
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = local.tags
}

# HTTP listener (optional)
resource "aws_lb_listener" "http" {
  count             = var.create_alb ? 1 : 0
  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}
