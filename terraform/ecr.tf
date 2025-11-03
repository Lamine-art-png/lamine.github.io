# Use the repo if it already exists
data "aws_ecr_repository" "api" {
  name = "${var.project}-api"
}

output "ecr_repo_url" {
  value = data.aws_ecr_repository.api.repository_url
}
