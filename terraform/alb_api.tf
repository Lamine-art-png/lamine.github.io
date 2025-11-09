resource "aws_lb" "api" {
  name               = "api-agroai-pilot-alb-default"  # EXACTLY as in AWS
  load_balancer_type = "application"
  internal           = false

  security_groups = [aws_security_group.alb_api.id]
  subnets         = var.public_subnet_ids  # whatever the ALB is actually using

  # Any other attributes should match what the existing ALB has:
  # - idle_timeout
  # - enable_deletion_protection
  # - ip_address_type
  # etc, or omit them so Terraform doesn't think it must change them.
  
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
