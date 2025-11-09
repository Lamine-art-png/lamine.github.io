resource "aws_lb" "api" {
  # Create a new ALB in the tasks’ VPC
  name               = "api-agroai-pilot-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb_api.id]
  subnets            = var.public_subnet_ids

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

# Use the TG you want the service to register to (port 8000 in the 0c4cf... VPC).
# If you already imported an existing TG (e.g., tg-api-8000-tf), make the
# name/port/vpc match that object to avoid replacement.
resource "aws_lb_target_group" "api" {
  name        = "tg-api-8000-tf"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

# HTTP -> HTTPS redirect
resource "aws_lb_listener" "api_http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS -> forward to TG
resource "aws_lb_listener" "api_https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-Res-2021-06"
  certificate_arn   = data.aws_acm_certificate.api.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
