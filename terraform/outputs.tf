output "alb_dns_name" {
  description = "DNS name of the API ALB"
  value       = aws_lb.api.dns_name
}

output "api_url" {
  description = "Base URL for the API"
  value       = "https://${aws_lb.api.dns_name}"
}
