resource "aws_ecr_repository" "api" {
  name                 = "${var.project}-api"
  image_scanning_configuration { scan_on_push = true }
  force_delete         = true
  tags = { Project = var.project, ManagedBy = "terraform" }
}

output "ecr_repo_url" {
  value = aws_ecr_repository.api.repository_url
}
