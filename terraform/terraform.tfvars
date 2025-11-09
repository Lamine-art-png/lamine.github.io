project           = "agroai-manulife-pilot"
aws_region        = "us-west-1"
container_port    = 8000
health_check_path = "/v1/health"
vpc_id            = "vpc-08c26202f480ac757"

public_subnet_ids = [
  "subnet-037e57b86892998a9",
  "subnet-05475eccb2a806e7b",
]

private_subnet_ids = [
  "subnet-037e57b86892998a9",
  "subnet-05475eccb2a806e7b",
]

api_image = "292039821285.dkr.ecr.us-west-1.amazonaws.com/agroai-manulife-pilot-api:latest"
