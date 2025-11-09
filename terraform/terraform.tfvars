project           = "agroai-manulife-pilot"
aws_region        = "us-west-1"
container_port    = 8000
health_check_path = "/v1/health"
vpc_id = "vpc-08c26202f480ac757"

public_subnet_ids = [
  "subnet-0893f781618a8f515",
  "subnet-06a73ccb1891253be",
]

private_subnet_ids = [
  "subnet-07d6bf0c6222e9545",
  "subnet-0e05e32b4c4e4be5e",
]

api_image = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api:latest"
