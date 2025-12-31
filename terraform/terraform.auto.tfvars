aws_region = "us-west-1"

# DO NOT change project if it already matches existing resources
project = "agroai-manulife-pilot"

vpc_id = "vpc-08c26202f480ac757"

public_subnet_ids = [
  "subnet-0893f781618a8f515",
  "subnet-06a73ccb1891253be",
]

ecs_subnet_ids = [
  "subnet-07d6bf0c6222e9545",
  "subnet-0e05e32b4c4e4be5e"
]
ecr_repository = "agroai-manulife-pilot-api"

