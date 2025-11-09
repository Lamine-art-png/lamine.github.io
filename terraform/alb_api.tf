resource "aws_lb" "api" {
  # Must match the existing ALB you are adopting
  name               = "api-agroai-pilot-alb-default"
  load_balancer_type = "application"
  internal           = false

  security_groups = [aws_security_group.alb_api.id]
  subnets         = var.public_subnet_ids  # must all be in var.vpc_id

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

resource "aws_lb_target_group" "api" {
  # Must match the existing TG you are adopting, or the desired new one
  name        = "tg-api-8000"
  port        = 80            # <-- use 80 *or* 8000, but it must match reality + ECS task/container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id    # e.g. vpc-08c26202f480ac757

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

# HTTP :80 -> redirect to HTTPS :443
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

# HTTPS :443 -> forward to target group
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
