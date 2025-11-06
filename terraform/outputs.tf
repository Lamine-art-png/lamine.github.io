output "alb_dns_name" {
  description = "ALB DNS name (if created)"
  value       = var.create_alb && length(aws_lb.api) > 0 ? aws_lb.api[0].dns_name : null
}

output "api_url" {
  description = "Public URL if behind ALB (currently empty because create_alb = false)"
  value       = var.create_alb && length(aws_lb.api) > 0 ? "http://${aws_lb.api[0].dns_name}" : ""
}
