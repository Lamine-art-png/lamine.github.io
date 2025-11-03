variable "region" {
  type    = string
  default = "us-west-1"
}

variable "project" {
  type    = string
  default = "agroai-manulife-pilot"
}

variable "desired_count" {
  type    = number
  default = 1
}

# CI will override this with TF_VAR_service_name; default is fine locally
variable "service_name" {
  type    = string
  default = "agroai-manulife-pilot-api"
}
