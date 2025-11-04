data "aws_ecr_repository" "api" {
  name = "${var.project}-api"
}

# optional, useful for debugging
output "ecr_repo_url" {
  value = data.aws_ecr_repository.api.repository_url
}
