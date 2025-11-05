# ecr.tf (keep only this one)
data "aws_ecr_repository" "api" {
  # pick ONE naming scheme and stick to it:
  # Option A (explicit name):
  name = "agroai-manulife-pilot-api"
  # Option B (derived name):
  # name = "${var.project}-api"
}
