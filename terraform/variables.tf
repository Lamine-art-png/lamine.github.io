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
  description = "Docker image tag to deploy (usually a git SHA)"
  type        = string
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

variable "wiseconn_api_key" {
  type        = string
  description = "WiseConn API key"
  sensitive   = true
  default     = ""
}

variable "database_url" {
  type        = string
  description = "PostgreSQL connection string"
  sensitive   = true
  default     = ""
}

variable "secret_key" {
  type        = string
  description = "Application secret key for JWT signing"
  sensitive   = true
  default     = ""
}

variable "db_subnet_ids" {
  type        = list(string)
  description = "Private subnets for RDS"
  default     = []
}

variable "sync_interval_minutes" {
  type        = number
  description = "WiseConn sync interval in minutes"
  default     = 15
}

