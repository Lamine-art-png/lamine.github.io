project           = "agroai-manulife-pilot"
aws_region        = "us-west-1"
container_port    = 8000
health_check_path = "/v1/health"
vpc_id            = "vpc-0c4cf14e0f5f0f680"

public_subnet_ids = [
  "subnet-037e57b86892998a9",
  "subnet-05475eccb2a806e7b",
]

private_subnet_ids = [
  "subnet-037e57b86892998a9",
  "subnet-05475eccb2a806e7b",
]


image_tag = "v1.69-9c56e1c"
