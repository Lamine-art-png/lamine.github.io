variable "project" {
  description = "Project name prefix"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "container_port" {
  description = "Container port exposed by the API"
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "HTTP path for health check"
  type        = string
  default     = "/healthz"
}
