variable "project"       { type = string default = "agroai-manulife-pilot" }
variable "aws_region"    { type = string default = "us-west-1" }
variable "container_image" { type = string default = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api" }
variable "health_check_path" { type = string default = "/" }
