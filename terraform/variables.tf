variable "project" {
  type        = string
  description = "Project name prefix"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID for all networking"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets (ALB typically lives here)"
}

variable "ecs_subnet_ids" {
  type        = list(string)
  description = "Subnets for ECS tasks"
}

variable "api_container_port" {
  type        = number
  description = "Container port for the API"
  default     = 8000
}

variable "image_tag" {
  type        = string
  description = "ECR image tag to deploy"
  default     = "latest"
}

variable "openweather_api_key" {
  type        = string
  description = "OpenWeather API key"
  sensitive   = true

  validation {
    condition     = length(trimspace(var.openweather_api_key)) > 0
    error_message = "openweather_api_key must be set (TF_VAR_openweather_api_key or -var)."
  }
}

