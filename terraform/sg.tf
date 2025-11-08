resource "aws_security_group" "alb_api" {
  # MUST match the existing SG in AWS / terraform state show
  name        = "alb-api-sg"
  description = "Public ALB for api-agroai-pilot.com"
  vpc_id      = "vpc-08c26202f480ac757"  # set this to exactly what the real SG uses

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project   = "agroai-manulife-pilot"
    ManagedBy = "terraform"
  }
}
