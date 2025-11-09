############################
# ALB security group (TF)
############################

resource "aws_security_group" "alb_api" {
  name        = "alb-api-sg-tf"
  description = "ALB for api-agroai-pilot.com"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from anywhere"
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
# We are ADOPTING it, not replacing it.
##########################################

resource "aws_security_group" "ecs_api" {
  # MUST match the real SG attributes that already exist
  name        = "agroai-manulife-pilot-ecs-tasks"
  description = "Allow inbound HTTP to API tasks"
  vpc_id      = "vpc-0c4cf14e0f5f0f680"

  # Keep the original rule (from legacy ALB SG)
  ingress {
    description    = "from legacy ALB SG"
    from_port      = 8000
    to_port        = 8000
    protocol       = "tcp"
    security_groups = ["sg-0069e0001aaff32e0"]
  }

  # ALSO allow traffic from the new TF-managed ALB SG
  ingress {
    description    = "from new ALB SG"
    from_port      = 8000
    to_port        = 8000
    protocol       = "tcp"
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

  # So future description tweaks don't trigger ForceNew hell
  lifecycle {
    ignore_changes = [description]
  }
}
