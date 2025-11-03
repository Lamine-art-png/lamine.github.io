variable "region" {
  type    = string
  default = "us-west-1"
}

variable "project" {
  type    = string
  default = "agroai-manulife-pilot"
}

# Optional: CI can override with TF_VAR_service_name
variable "service_name" {
  type    = string
  default = ""
}

variable "desired_count" {
  type    = number
  default = 1
}
