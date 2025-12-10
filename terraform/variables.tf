kkvariable "project" {
  type        = string
  description = "Project name prefix"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID for all networking"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets for the ALB"
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
  description = "Docker image tag for the API container"
  default     = "latest"
}

variable "openweather_api_key" {
  type        = string
  description = "OpenWeather API key"
  sensitive   = true
}

