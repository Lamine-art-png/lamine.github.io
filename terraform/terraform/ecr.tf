# terraform/ecr.tf
resource "aws_ecr_repository" "api" {
  name = "${var.project}-api"   # e.g., agroai-manulife-pilot-api
  image_scanning_configuration { scan_on_push = true }
  force_delete = true
}
