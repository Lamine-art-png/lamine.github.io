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

/* Optional. CI will pass a unique value to avoid name/log-group collisions. */
variable "service_name" {
  type    = string
  default = ""  # when empty, we'll derive from var.project
}
