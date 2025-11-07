variable "project" {
  type        = string
  default     = "agroai-manulife-pilot"
}

variable "aws_region" {
  type        = string
  default     = "us-west-1"
}

variable "container_port" {
  type        = number
  default     = 8000
}

variable "health_check_path" {
  type        = string
  default     = "/v1/health"
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "api_image" {
  type        = string
  description = "Full image URI for the API task (set via CI/CD)"
  default     = "" # or leave unset and pass via -var / tfvars in CI
}
