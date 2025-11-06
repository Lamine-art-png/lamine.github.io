output "alb_dns_name" {
  description = "ALB DNS name (empty if ALB not created)"
  value       = var.create_alb && length(aws_lb.api) > 0 ? aws_lb.api[0].dns_name : ""
}

output "api_url" {
  description = "API URL (custom domain if set; otherwise ALB DNS; empty if no ALB)"
  value = (
    var.domain_name != ""
      ? "https://${var.domain_name}"
      : (
          var.create_alb && length(aws_lb.api) > 0
            ? "http://${aws_lb.api[0].dns_name}"
            : ""
        )
  )
}
