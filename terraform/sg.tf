resource "aws_security_group" "alb_api" {
  name        = "alb-api-sg-tf"
  description = "ALB for api.agroai-pilot.com"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

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

# IMPORTANT: this must match sg-0e3350ce8b6707462 exactly
resource "aws_security_group" "ecs_api" {
  name        = "agroai-manulife-pilot-ecs-tasks"
  description = "Allow inbound HTTP to API tasks"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    # Existing SG it trusts today:
    security_groups = ["sg-0069e0001aaff32e0"]
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
