variable "project" {
  type    = string
  default = "agroai-manulife-pilot"
}

variable "aws_region" {
  type    = string
  default = "us-west-1"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "health_check_path" {
  type    = string
  default = "/"
}

variable "create_alb" {
  description = "If true, create ALB + listeners + SG and (later) wire ECS service to it."
  type        = bool
  default     = false  # keep false until AWS lifts your ELB restriction
}

variable "api_image" {
  description = "ECR image:tag for the API. If empty, ':latest' in the repo is used."
  type        = string
  default     = ""
}
