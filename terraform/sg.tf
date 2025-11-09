##########################################
# ECS tasks SG — existing sg-0e3350ce8b6707462
##########################################

resource "aws_security_group" "ecs_api" {
  name        = "agroai-manulife-pilot-ecs-tasks"
  # MUST match the real SG to avoid replacement
  description = "Allow inbound HTTP to API tasks"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

  # Original rule: from legacy ALB SG
  ingress {
    description     = "from legacy ALB SG"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = ["sg-0069e0001aaff32e0"]
  }

  # New rule: from TF-managed ALB SG
  ingress {
    description     = "from new ALB SG"
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
