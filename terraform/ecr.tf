# Use the existing ECR repo for the image URL
data "aws_ecr_repository" "api" {
  name = "${var.project}-api"
}
