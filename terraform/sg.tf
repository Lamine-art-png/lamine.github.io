resource "aws_security_group" "alb_api" {
  # MUST match the existing SG in AWS / terraform state
  name        = "alb-api-sg"
  description = "Public ALB for api-agroai-pilot.com"
  vpc_id      = "vpc-08c26202f480ac757" # <-- use exactly what AWS shows for sg-01a446eb1458eb7cf

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

resource "aws_security_group" "ecs_api" {
  # MUST also match the existing ECS-tasks SG you imported
  name        = "agroai-manulife-pilot-ecs-tasks"
  description = "Allow inbound HTTP to API tasks"
  vpc_id      = "vpc-0c4cf14e0f5f0f680" # or whatever AWS shows for sg-0e3350ce8b6707462

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
}
