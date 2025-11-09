##########################################
# ALB security group (TF managed)
##########################################

resource "aws_security_group" "alb_api" {
  name        = "alb-api-sg-tf"
  description = "ALB for api-agroai-pilot.com"
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

##########################################
# ECS tasks SG — existing sg-0e3350ce8b6707462
##########################################

##########################################
# ECS tasks SG — existing sg-0e3350ce8b6707462
##########################################

resource "aws_security_group" "ecs_api" {
  name        = "agroai-manulife-pilot-ecs-tasks"
  description = "Allow inbound HTTP to API tasks"  # must match existing
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

  # Existing rule from legacy ALB SG (matches current state)
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = ["sg-0069e0001aaff32e0"]
  }

  # New rule from TF-managed ALB SG
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_api.id]
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

  lifecycle {
    ignore_changes = [description]
  }
}
