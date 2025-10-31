variable "region"        { type = string  default = "us-west-1" }
variable "project"       { type = string  default = "agroai-manulife-pilot" }
variable "env"           { type = string  default = "dev" }
variable "vpc_cidr"      { type = string  default = "10.42.0.0/16" }
variable "desired_count" { type = number  default = 1 }

