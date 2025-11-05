variable "project" {
  description = "Name/prefix for tags and resources"
  type        = string
  default     = "agroai-manulife-pilot"
}

variable "aws_region" {
  description = "AWS region to deploy into (used by the provider)"
  type        = string
  default     = "us-west-1"
}

variable "container_port" {
  description = "Container/app listening port (must match your app & SG)"
  type        = number
  default     = 80
  validation {
    condition     = var.container_port >= 1 && var.container_port <= 65535
    error_message = "container_port must be between 1 and 65535."
  }
}

variable "health_check_path" {
  description = "HTTP path the container must return 200 on"
  type        = string
  default     = "/"
  validation {
    condition     = can(regex("^/", var.health_check_path))
    error_message = "health_check_path must start with '/'."
  }
}
