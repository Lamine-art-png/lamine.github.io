resource "aws_lb" "api" {
  name               = "api-agroai-pilot-alb-default"  # must match
  load_balancer_type = "application"
  internal           = false

  security_groups = [aws_security_group.alb_api.id]
  subnets         = var.public_subnet_ids

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "tg-api-8000"                     # match existing
  port        = 80                                # match existing
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id                        # vpc-08c26202f480ac757

  health_check {
    enabled             = true
    path                = "/v1/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 5
    unhealthy_threshold = 2
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
