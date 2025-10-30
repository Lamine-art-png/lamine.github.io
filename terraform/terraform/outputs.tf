# terraform/outputs.tf
output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "cluster_arn" {
  value = try(module.ecs.cluster_arn, null)
}

output "db_endpoint" {
  value = try(module.db.db_instance_endpoint, module.db.db_instance_address, null)
}

output "db_port" {
  value = try(module.db.db_instance_port, 5432)
}
