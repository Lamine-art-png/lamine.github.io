output "alb_dns_name" {
  description = "DNS name of the API ALB"
  value       = "api-agroai-pilot-alb-tf-746939467.us-west-1.elb.amazonaws.com"
}

output "api_url" {
  description = "Base URL for the API"
  value       = "https://api-agroai-pilot-alb-tf-746939467.us-west-1.elb.amazonaws.com"
}
