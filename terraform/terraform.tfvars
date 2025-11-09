project           = "agroai-manulife-pilot"
aws_region        = "us-west-1"
container_port    = 8000
health_check_path = "/v1/health"
vpc_id = "vpc-08c26202f480ac757"

public_subnet_ids = [
  "subnet-0893f781618a8f515", # public us-west-1c
  "subnet-06a73ccb1891253be", # public us-west-1a
]

private_subnet_ids = [
  "subnet-07d6bfc6222e9645",  # private us-west-1c
  "subnet-00e532b4c4e4be5e",  # private us-west-1a
]

api_image = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api:latest"
