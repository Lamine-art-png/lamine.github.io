resource "aws_lb" "api" {
  name               = "api-agroai-pilot-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_api.id]
  subnets            = var.public_subnet_ids

  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "tg-api-8000-tf"      # match existing if you don’t want replacement
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    path = "/v1/health"
  }

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

# HTTP 80 -> redirect to HTTPS
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

# HTTPS 443 -> forward to target group
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
