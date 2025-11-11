##########################################
# ALB SG
##########################################

resource "aws_security_group" "alb_api" {
  name        = "alb-api-sg-tf"
  description = "ALB for api-agroai-pilot"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
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
# ECS tasks SG
##########################################

resource "aws_security_group" "ecs_api" {
  name        = "agroai-manulife-pilot-ecs-tasks-tf"
  description = "Allow inbound 8000 from ALB to ECS tasks"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

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

