# main.tf (root)
provider "aws" { region = var.region }

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "in_default_vpc" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_security_group" "api_sg" { ... }

module "ecs" { ... }

module "api_service" {
  ...
  subnet_ids = slice(data.aws_subnets.in_default_vpc.ids, 0, 2)
  ...
}
