variable "project"      { type = string  default = "agroai-manulife-pilot" }
variable "region"       { type = string  default = "us-west-1" }
variable "vpc_cidr"     { type = string  default = "10.42.0.0/16" }
variable "db_instance"  { type = string  default = "db.t3.micro" }
variable "db_name"      { type = string  default = "agroai" }
variable "db_username"  { type = string  default = "agroadmin" }
variable "api_image"    { type = string  description = "ECR image:tag for API" }
variable "desired_count"{ type = number  default = 1 }
variable "env"          { type = string  default = "pilot" }
