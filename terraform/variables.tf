variable "project" {
  type    = string
  default = "agroai-manulife-pilot"
}

variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "health_check_path" {
  type    = string
  default = "/healthz"
}
variable "domain_name" {
  description = "Optional hostname for the API (e.g., api.example.com). Leave blank to use the ALB DNS."
  type        = string
  default     = ""
}

