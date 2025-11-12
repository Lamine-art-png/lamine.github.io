#########################
# IAM for ECS
#########################

# Role used by the ECS agent (pull image, push logs)
resource "aws_iam_role" "ecs_task_execution" {
  name = "ecsTaskExecutionRole-${var.project}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
      }
    ]
  })

  tags = { Project = var.project }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Trust policy for your *application* task role
data "aws_iam_policy_document" "ecs_task_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# App task role (your code runs with this role)
resource "aws_iam_role" "ecs_task" {
  name               = "${var.project}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_trust.json
  tags               = { Project = var.project }
}

# (Optional) attach more policies to the app role later
# resource "aws_iam_role_policy_attachment" "ssm_read" {
#   role       = aws_iam_role.ecs_task.name
#   policy_arn = "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess"
# }

