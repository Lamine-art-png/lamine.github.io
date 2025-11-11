# Assume data.aws_acm_certificate.api is already defined ONCE elsewhere

resource "aws_lb" "api" {
  name               = "api-agroai-pilot-alb-tf" # new unique name
  load_balancer_type = "application"
  internal           = false

  subnets = [
    "subnet-037e57b86892998a9",
    "subnet-05475eccb2a806e7b",
  ]

  security_groups = [aws_security_group.alb_api.id]

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "tg-api-8000-tf"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

  health_check {
    path    = "/v1/health"
    matcher = "200"
  }

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

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

