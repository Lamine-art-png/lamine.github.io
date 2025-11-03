variable "region"        { type = string  default = "us-west-1" }
variable "project"       { type = string  default = "agroai-manulife-pilot" }
variable "desired_count" { type = number  default = 1 }
variable "vpc_cidr"      { type = string  default = "10.42.0.0/16" }

# Will be overridden by CI so every run uses a unique ECS service/log group name
variable "service_name"  { type = string  default = "agroai-manulife-pilot-api-v2" }
